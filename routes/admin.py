"""
Admin panel.
This file merges two things that had drifted apart:
  1. The "scrutinize per course-offering" workflow (dashboard, scrutinize,
     process_scrutiny, publish_semester, knock_faculty, override_marks) —
     kept exactly as it was working.
  2. The "individual pages" set (Faculty Approvals, Payments, Complaints,
     Routine & Offerings, Accounts, Result Review, Publish Results) that
     your sidebar and several templates already expect but were missing
     from this file — added below.

NOTE: dashboard.html's "Publish Semester Results" card and the dedicated
Publish Results page (approved_results/publish_results) are now two
separate ways to publish the same thing. Both work independently and
won't conflict, but it's worth eventually picking one and removing the
other so you're not maintaining two publish UIs.
"""

from functools import wraps
from datetime import datetime
from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from database import get_db

try:
    from utils.gpa_calculator import marks_to_grade, get_grade_point, determine_completion
except ModuleNotFoundError:
    from ..utils.gpa_calculator import marks_to_grade, get_grade_point, determine_completion

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get('role') != 'admin' or 'user_id' not in session:
            flash("Please sign in as an admin to continue.", "error")
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return wrapper


# ============================================================
# DASHBOARD (unchanged from your current version)
# ============================================================
@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT * FROM staff WHERE id = %s", (session.get('user_id'),))
    admin = cur.fetchone()

    cur.execute("""
        SELECT co.id AS offering_id, c.course_code, c.course_name, sem.name AS semester_name,
               st.name AS faculty_name,
               COUNT(e.id) AS total_submissions
        FROM course_offerings co
        JOIN courses c ON co.course_id = c.id
        JOIN semesters sem ON co.semester_id = sem.id
        JOIN staff st ON co.faculty_id = st.id
        JOIN enrollments e ON e.course_offering_id = co.id
        WHERE e.submission_status = 'submitted_by_faculty'
        GROUP BY co.id, c.course_code, c.course_name, sem.name, st.name
    """)
    pending_submissions = cur.fetchall()

    cur.execute("""
        SELECT rc.id AS complaint_id, rc.reason, rc.status, rc.created_at,
               s.name AS student_name, s.student_id AS student_code,
               c.course_code, c.course_name, st.name AS faculty_name, e.course_offering_id
        FROM result_complaints rc
        JOIN enrollments e ON rc.enrollment_id = e.id
        JOIN students s ON e.student_id = s.id
        JOIN course_offerings co ON e.course_offering_id = co.id
        JOIN courses c ON co.course_id = c.id
        JOIN staff st ON co.faculty_id = st.id
        WHERE rc.status = 'pending'
        ORDER BY rc.created_at DESC
    """)
    complaints = cur.fetchall()

    cur.execute("SELECT * FROM semesters ORDER BY is_current DESC, id DESC")
    semesters = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        'admin/dashboard.html',
        admin=admin,
        pending_submissions=pending_submissions,
        complaints=complaints,
        semesters=semesters
    )


# ============================================================
# SCRUTINIZE (unchanged, plus the 3 missing endpoints it calls)
# ============================================================
@admin_bp.route('/scrutinize/<int:offering_id>')
@admin_required
def scrutinize(offering_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT co.id, c.course_code, c.course_name, sem.name AS semester_name, st.name AS faculty_name
        FROM course_offerings co
        JOIN courses c ON co.course_id = c.id
        JOIN semesters sem ON co.semester_id = sem.id
        JOIN staff st ON co.faculty_id = st.id
        WHERE co.id = %s
    """, (offering_id,))
    offering = cur.fetchone()

    cur.execute("""
        SELECT e.id, e.marks_obtained, e.continuous_marks, e.final_exam_marks,
               e.grade, e.grade_point, e.exam_attendance, e.submission_status,
               st.name AS student_name, st.student_id
        FROM enrollments e
        JOIN students st ON e.student_id = st.id
        WHERE e.course_offering_id = %s AND e.submission_status = 'submitted_by_faculty'
        ORDER BY st.student_id
    """, (offering_id,))
    grades = cur.fetchall()

    pass_count = sum(1 for g in grades if g['grade'] and g['grade'] != 'F')
    fail_count = sum(1 for g in grades if g['grade'] == 'F' or g['exam_attendance'] == 'absent')
    marks_list = [float(g['marks_obtained']) for g in grades if g['marks_obtained'] is not None]
    average_marks = round(sum(marks_list) / len(marks_list), 1) if marks_list else 0.0

    cur.close()
    conn.close()

    return render_template(
        'admin/scrutinize.html',
        offering=offering,
        grades=grades,
        pass_count=pass_count,
        fail_count=fail_count,
        average_marks=average_marks,
    )


def _run_scrutiny_action(offering_id, action, remarks):
    """Shared logic for approve/reject, called by both the combined
    process_scrutiny route and the two dedicated approve/reject routes."""
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    if action == 'approve':
        cur.execute("""
            SELECT id, marks_obtained, exam_attendance
            FROM enrollments
            WHERE course_offering_id = %s AND submission_status = 'submitted_by_faculty'
        """, (offering_id,))
        submitted_records = cur.fetchall()

        for record in submitted_records:
            marks = record['marks_obtained']
            attendance = record['exam_attendance']
            letter_grade = marks_to_grade(marks)
            grade_pt = get_grade_point(letter_grade)
            credit_completed, is_supplementary = determine_completion(letter_grade, attendance)

            cur.execute("""
                UPDATE enrollments
                SET submission_status = 'approved_by_admin',
                    grade = %s, grade_point = %s,
                    credit_completed = %s, is_supplementary = %s,
                    approved_by = %s, approved_at = %s
                WHERE id = %s
            """, (letter_grade, grade_pt, credit_completed, is_supplementary,
                  session.get('user_id'), datetime.now(), record['id']))

        flash("Marks successfully approved after scrutinization.", "success")

    elif action == 'reject':
        cur.execute("""
            UPDATE enrollments
            SET submission_status = 'not_submitted', admin_remarks = %s
            WHERE course_offering_id = %s AND submission_status = 'submitted_by_faculty'
        """, (remarks or "Admin requested recalculation/correction.", offering_id))
        flash("Marks rejected and returned to faculty for re-entry.", "error")

    conn.commit()
    cur.close()
    conn.close()


@admin_bp.route('/scrutinize/<int:offering_id>/action', methods=['POST'])
@admin_required
def process_scrutiny(offering_id):
    action = request.form.get('action')
    remarks = request.form.get('admin_remarks', '').strip()
    _run_scrutiny_action(offering_id, action, remarks)
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/scrutinize/<int:offering_id>/approve', methods=['POST'])
@admin_required
def approve_submission(offering_id):
    """Dedicated endpoint for scrutinize.html's 'Approve & Lock' button."""
    _run_scrutiny_action(offering_id, 'approve', '')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/scrutinize/<int:offering_id>/reject', methods=['POST'])
@admin_required
def reject_submission(offering_id):
    """Dedicated endpoint for scrutinize.html's 'Request Revision' button."""
    remarks = request.form.get('admin_remarks', '').strip()
    _run_scrutiny_action(offering_id, 'reject', remarks)
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/scrutinize/override-marks', methods=['POST'])
@admin_required
def override_marks():
    """Manual mark override with a mandatory audit-trail reason (scrutinize.html modal)."""
    enrollment_id = request.form.get('grade_id', type=int)
    offering_id = request.form.get('offering_id', type=int)
    continuous = request.form.get('continuous_marks', type=float)
    final_exam = request.form.get('final_exam_marks', type=float)
    reason = request.form.get('reason', '').strip()

    if not enrollment_id or continuous is None or final_exam is None or not reason:
        flash("All fields are required to override marks.", "error")
        return redirect(url_for('admin.scrutinize', offering_id=offering_id))

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT continuous_marks, final_exam_marks FROM enrollments WHERE id = %s", (enrollment_id,))
    old = cur.fetchone()

    total_marks = continuous + final_exam
    letter_grade = marks_to_grade(total_marks)
    grade_pt = get_grade_point(letter_grade)

    cur.execute("""
        UPDATE enrollments
        SET continuous_marks = %s, final_exam_marks = %s, marks_obtained = %s,
            grade = %s, grade_point = %s
        WHERE id = %s
    """, (continuous, final_exam, total_marks, letter_grade, grade_pt, enrollment_id))

    cur.execute("""
        INSERT INTO grade_audit_logs
            (enrollment_id, admin_id, old_continuous, new_continuous, old_final, new_final, reason)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (enrollment_id, session['user_id'], old['continuous_marks'], continuous,
          old['final_exam_marks'], final_exam, reason))

    conn.commit()
    cur.close()
    conn.close()

    flash("Marks overridden and logged.", "success")
    return redirect(url_for('admin.scrutinize', offering_id=offering_id))


# ============================================================
# PUBLISH (unchanged)
# ============================================================
@admin_bp.route('/publish-semester/<int:semester_id>', methods=['POST'])
@admin_required
def publish_semester(semester_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE enrollments e
        JOIN course_offerings co ON e.course_offering_id = co.id
        SET e.submission_status = 'published', e.is_locked = TRUE
        WHERE co.semester_id = %s AND e.submission_status = 'approved_by_admin'
    """, (semester_id,))
    count = cur.rowcount

    if count > 0:
        cur.execute("""
            UPDATE semesters SET result_published = TRUE, result_publish_date = %s WHERE id = %s
        """, (datetime.now(), semester_id))

    conn.commit()
    cur.close()
    conn.close()
    flash(f"Published results for {count} enrollment(s). Students can now view their grades.", "success")
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/complaint/<int:complaint_id>/knock-faculty', methods=['POST'])
@admin_required
def knock_faculty(complaint_id):
    admin_note = request.form.get('admin_note', '').strip()
    formatted_remark = f"COMPLAINT REVIEW REQUEST: {admin_note}" if admin_note else "COMPLAINT REVIEW REQUEST: Admin requested re-verification."

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT * FROM result_complaints WHERE id = %s", (complaint_id,))
    complaint = cur.fetchone()

    if complaint:
        cur.execute("UPDATE result_complaints SET status = 'sent_to_faculty' WHERE id = %s", (complaint_id,))
        cur.execute("""
            UPDATE enrollments
            SET submission_status = 'not_submitted', is_locked = FALSE, admin_remarks = %s
            WHERE id = %s
        """, (formatted_remark, complaint['enrollment_id']))
        conn.commit()
        flash("Complaint forwarded to the respective faculty member for review.", "success")
    else:
        flash("Complaint not found.", "error")

    cur.close()
    conn.close()
    return redirect(url_for('admin.dashboard'))


# ============================================================
# FACULTY APPROVALS
# ============================================================
@admin_bp.route('/faculty-approvals')
@admin_required
def faculty_approvals():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT id, staff_id, name, email, role, approval_status, created_at
        FROM staff WHERE approval_status = 'pending'
        ORDER BY created_at ASC
    """)
    pending = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('admin/faculty_approvals.html', pending=pending)


@admin_bp.route('/faculty-approvals/<int:staff_id>/approve', methods=['POST'])
@admin_required
def approve_faculty(staff_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE staff SET approval_status = 'approved' WHERE id = %s", (staff_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Account approved. They can now log in.", "success")
    return redirect(url_for('admin.faculty_approvals'))


@admin_bp.route('/faculty-approvals/<int:staff_id>/reject', methods=['POST'])
@admin_required
def reject_faculty(staff_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE staff SET approval_status = 'rejected' WHERE id = %s", (staff_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Account rejected.", "success")
    return redirect(url_for('admin.faculty_approvals'))


# ============================================================
# PAYMENTS
# ============================================================
@admin_bp.route('/payments')
@admin_required
def payments():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    status_filter = request.args.get('status', 'pending')
    query = """
        SELECT p.*, s.name AS student_name, s.student_id, sem.name AS semester_name
        FROM payments p
        JOIN students s ON p.student_id = s.id
        JOIN semesters sem ON p.semester_id = sem.id
    """
    params = ()
    if status_filter in ('pending', 'verified', 'rejected'):
        query += " WHERE p.status = %s"
        params = (status_filter,)
    query += " ORDER BY p.submitted_at DESC"
    cur.execute(query, params)
    payment_rows = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('admin/payments.html', payments=payment_rows, status_filter=status_filter)


@admin_bp.route('/payments/<int:payment_id>/verify', methods=['POST'])
@admin_required
def verify_payment(payment_id):
    conn = get_db()
    cur = conn.cursor()
    admin_id = session['user_id']
    receipt_no = 'RCPT-' + datetime.now().strftime('%Y%m%d%H%M%S')
    cur.execute("""
        UPDATE payments
        SET status = 'verified', receipt_no = %s, verified_by = %s, verified_at = NOW()
        WHERE id = %s
    """, (receipt_no, admin_id, payment_id))
    conn.commit()
    cur.close()
    conn.close()
    flash(f"Payment verified. Receipt {receipt_no} issued.", "success")
    return redirect(url_for('admin.payments'))


@admin_bp.route('/payments/<int:payment_id>/reject', methods=['POST'])
@admin_required
def reject_payment(payment_id):
    conn = get_db()
    cur = conn.cursor()
    admin_id = session['user_id']
    cur.execute("""
        UPDATE payments SET status = 'rejected', verified_by = %s, verified_at = NOW() WHERE id = %s
    """, (admin_id, payment_id))
    conn.commit()
    cur.close()
    conn.close()
    flash("Payment rejected. The student can resubmit.", "success")
    return redirect(url_for('admin.payments'))


# ============================================================
# COMPLAINTS (general 4-category complaints — separate from result_complaints)
# ============================================================
@admin_bp.route('/complaints')
@admin_required
def complaints():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    status_filter = request.args.get('status', 'pending')
    query = """
        SELECT c.*, s.name AS student_name, s.student_id
        FROM complaints c JOIN students s ON c.student_id = s.id
    """
    params = ()
    if status_filter in ('pending', 'resolved'):
        query += " WHERE c.status = %s"
        params = (status_filter,)
    query += " ORDER BY c.created_at DESC"
    cur.execute(query, params)
    complaint_rows = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('admin/complaints.html', complaints=complaint_rows, status_filter=status_filter)


@admin_bp.route('/complaints/<int:complaint_id>/resolve', methods=['POST'])
@admin_required
def resolve_complaint(complaint_id):
    conn = get_db()
    cur = conn.cursor()
    response_text = request.form.get('admin_response', '').strip()
    if not response_text:
        flash("Please write a response before resolving.", "error")
        return redirect(url_for('admin.complaints'))
    cur.execute("""
        UPDATE complaints SET status = 'resolved', admin_response = %s, resolved_at = NOW() WHERE id = %s
    """, (response_text, complaint_id))
    conn.commit()
    cur.close()
    conn.close()
    flash("Complaint marked resolved and student notified.", "success")
    return redirect(url_for('admin.complaints'))


# ============================================================
# SEMESTER MANAGEMENT
# Semesters are now created and controlled entirely by admin —
# nothing is hardcoded/seeded in schema.sql anymore.
# ============================================================
@admin_bp.route('/semesters')
@admin_required
def semesters():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM semesters ORDER BY is_current DESC, id DESC")
    semester_rows = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('admin/semesters.html', semesters=semester_rows)


@admin_bp.route('/semesters/create', methods=['POST'])
@admin_required
def create_semester():
    name = request.form.get('name', '').strip()
    make_current = request.form.get('make_current') == 'on'

    if not name:
        flash("Semester name is required.", "error")
        return redirect(url_for('admin.semesters'))

    conn = get_db()
    cur = conn.cursor()
    try:
        if make_current:
            cur.execute("UPDATE semesters SET is_current = FALSE")

        cur.execute("""
            INSERT INTO semesters (name, is_current)
            VALUES (%s, %s)
        """, (name, make_current))
        conn.commit()
        flash(f"Semester '{name}' created.", "success")
    except Exception as err:
        conn.rollback()
        flash(f"Error creating semester: {err}", "error")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin.semesters'))


@admin_bp.route('/semesters/<int:semester_id>/set-current', methods=['POST'])
@admin_required
def set_current_semester(semester_id):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE semesters SET is_current = FALSE")
        cur.execute("UPDATE semesters SET is_current = TRUE WHERE id = %s", (semester_id,))
        conn.commit()
        flash("Current semester updated.", "success")
    except Exception as err:
        conn.rollback()
        flash(f"Error: {err}", "error")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('admin.semesters'))


@admin_bp.route('/semesters/<int:semester_id>/delete', methods=['POST'])
@admin_required
def delete_semester(semester_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    # Block instead of silently cascading into course_offerings/payments
    cur.execute("SELECT COUNT(*) AS cnt FROM course_offerings WHERE semester_id = %s", (semester_id,))
    offering_count = cur.fetchone()['cnt']

    if offering_count > 0:
        flash(f"Cannot delete: {offering_count} course offering(s) still linked to this semester. Reassign or delete them first.", "error")
        cur.close(); conn.close()
        return redirect(url_for('admin.semesters'))

    cur.execute("DELETE FROM semesters WHERE id = %s", (semester_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Semester deleted.", "success")
    return redirect(url_for('admin.semesters'))


# ============================================================
# SEMESTER FEES (per-student, not per-semester — amounts can
# differ by department, waiver, individual arrangement, etc.)
# ============================================================
@admin_bp.route('/fees', methods=['GET', 'POST'])
@admin_required
def fees():
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT * FROM semesters WHERE is_current = TRUE LIMIT 1")
    current_semester = cur.fetchone()

    if request.method == 'POST':
        if not current_semester:
            flash("No current semester set — create/select one first.", "error")
        else:
            student_id = request.form.get('student_id', type=int)
            amount = request.form.get('amount_due', type=float)

            if not student_id or amount is None:
                flash("Student and amount are required.", "error")
            else:
                cur.execute("""
                    INSERT INTO student_fees (student_id, semester_id, amount_due, set_by)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE amount_due = VALUES(amount_due), set_by = VALUES(set_by)
                """, (student_id, current_semester['id'], amount, session['user_id']))
                conn.commit()
                flash("Fee set for student.", "success")

    cur.execute("SELECT id, student_id, name FROM students WHERE is_active = 1 ORDER BY name")
    all_students = cur.fetchall()

    fees_list = []
    if current_semester:
        cur.execute("""
            SELECT sf.amount_due, s.student_id AS student_code, s.name
            FROM student_fees sf
            JOIN students s ON sf.student_id = s.id
            WHERE sf.semester_id = %s
            ORDER BY s.name
        """, (current_semester['id'],))
        fees_list = cur.fetchall()

    cur.close()
    conn.close()
    return render_template(
        'admin/fees.html',
        current_semester=current_semester,
        all_students=all_students,
        fees_list=fees_list,
    )


# ============================================================
# CURRICULUM MANAGEMENT — assign credits/program/semester_level
# to courses through the panel, not manual SQL
# ============================================================
@admin_bp.route('/curriculum', methods=['GET', 'POST'])
@admin_required
def curriculum():
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    if request.method == 'POST':
        course_id = request.form.get('course_id', type=int)
        program = request.form.get('program', '').strip()
        credits = request.form.get('credits', type=float)
        semester_level = request.form.get('semester_level', '').strip() or None

        if not course_id or not program or credits is None:
            flash("Course, program, and credits are required.", "error")
        else:
            try:
                cur.execute("""
                    INSERT INTO curriculum (course_id, program, credits, semester_level)
                    VALUES (%s, %s, %s, %s)
                """, (course_id, program, credits, semester_level))
                conn.commit()
                flash("Curriculum entry added.", "success")
            except Exception as err:
                conn.rollback()
                flash(f"Error: {err}", "error")

    # Courses that still have NO curriculum row at all
    cur.execute("""
        SELECT c.id, c.course_code, c.course_name, d.short_form AS department
        FROM courses c
        LEFT JOIN curriculum crc ON crc.course_id = c.id
        LEFT JOIN departments d ON c.department_id = d.id
        WHERE crc.id IS NULL
        ORDER BY d.short_form, c.course_code
    """)
    missing_courses = cur.fetchall()

    # Full curriculum listing (already-assigned courses)
    cur.execute("""
        SELECT crc.id, c.course_code, c.course_name, crc.program, crc.credits, crc.semester_level
        FROM curriculum crc
        JOIN courses c ON crc.course_id = c.id
        ORDER BY crc.semester_level, c.course_code
    """)
    assigned = cur.fetchall()

    cur.close()
    conn.close()
    return render_template(
        'admin/curriculum.html',
        missing_courses=missing_courses,
        assigned=assigned,
    )


@admin_bp.route('/curriculum/<int:curriculum_id>/delete', methods=['POST'])
@admin_required
def delete_curriculum(curriculum_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM curriculum WHERE id = %s", (curriculum_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Curriculum entry removed.", "success")
    return redirect(url_for('admin.curriculum'))


# ============================================================
# ROUTINE & OFFERINGS
# ============================================================
@admin_bp.route('/routine-offerings', methods=['GET', 'POST'])
@admin_required
def routine_offerings():

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    if request.method == 'POST':

        course_id = request.form.get('course_id')
        semester_id = request.form.get('semester_id')
        faculty_id = request.form.get('faculty_id') or None
        class_time = request.form.get('class_time', '').strip()
        room = request.form.get('room', '').strip()

        if not course_id or not semester_id:
            flash("Course and semester are required.", "error")

        else:
            cur.execute("""
                INSERT INTO course_offerings
                (course_id, semester_id, faculty_id, class_time, room)
                VALUES (%s,%s,%s,%s,%s)
            """,
            (
                course_id,
                semester_id,
                faculty_id,
                class_time,
                room
            ))

            conn.commit()
            flash("Course offering created.", "success")


    # SHOW OFFERINGS
    cur.execute("""
        SELECT 
            co.id,
            c.course_code,
            c.course_name,
            d.short_form AS department,
            sem.name AS semester_name,
            st.name AS faculty_name,
            co.class_time,
            co.room

        FROM course_offerings co

        JOIN courses c
            ON co.course_id = c.id

        LEFT JOIN departments d
            ON c.department_id = d.id

        JOIN semesters sem
            ON co.semester_id = sem.id

        LEFT JOIN staff st
            ON co.faculty_id = st.id

        ORDER BY 
            d.short_form,
            c.course_code

    """)

    offerings = cur.fetchall()



    # COURSE DROPDOWN
    cur.execute("""
        SELECT 
            id,
            course_code,
            course_name

        FROM courses

        ORDER BY course_code
    """)

    all_courses = cur.fetchall()



    # SEMESTER DROPDOWN
    cur.execute("""
        SELECT id,name
        FROM semesters
        ORDER BY id DESC
    """)

    all_semesters = cur.fetchall()



    # FACULTY DROPDOWN
    cur.execute("""
        SELECT 
            id,
            name

        FROM staff

        WHERE role='faculty'
        AND approval_status='approved'

        ORDER BY name
    """)

    all_faculty = cur.fetchall()


    # CLASS TIME DROPDOWN
    cur.execute("""
        SELECT id, day_of_week, time_slot
        FROM class_times
        ORDER BY FIELD(day_of_week, 'Sunday','Monday','Tuesday','Wednesday','Thursday'), id
    """)
    all_class_times = cur.fetchall()


    # ROOM DROPDOWN
    cur.execute("""
        SELECT id, room_name
        FROM rooms
        ORDER BY room_name
    """)
    all_rooms = cur.fetchall()


    cur.close()
    conn.close()
    return render_template(
        'admin/routine_offerings.html',
        offerings=offerings,
        all_courses=all_courses,
        all_semesters=all_semesters,
        all_faculty=all_faculty,
        all_class_times=all_class_times,
        all_rooms=all_rooms
    )

@admin_bp.route('/routine-offerings/<int:offering_id>/delete', methods=['POST'])
@admin_required
def delete_offering(offering_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM course_offerings WHERE id = %s", (offering_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Course offering removed.", "success")
    return redirect(url_for('admin.routine_offerings'))


# ============================================================
# ACCOUNTS
# ============================================================
@admin_bp.route('/accounts')
@admin_required
def accounts():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    search = request.args.get('q', '').strip()

    student_query = "SELECT id, student_id, name, email, is_active, profile_locked FROM students"
    staff_query = "SELECT id, staff_id, name, email, role, approval_status, is_active FROM staff"
    params = ()
    if search:
        student_query += " WHERE name LIKE %s OR student_id LIKE %s OR email LIKE %s"
        staff_query += " WHERE name LIKE %s OR staff_id LIKE %s OR email LIKE %s"
        like = f"%{search}%"
        params = (like, like, like)
    student_query += " ORDER BY name"
    staff_query += " ORDER BY name"

    cur.execute(student_query, params)
    students = cur.fetchall()
    cur.execute(staff_query, params)
    staff = cur.fetchall()

    cur.close()
    conn.close()
    return render_template('admin/accounts.html', students=students, staff=staff, search=search)


@admin_bp.route('/accounts/student/<int:student_id>/toggle', methods=['POST'])
@admin_required
def toggle_student_account(student_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT is_active FROM students WHERE id = %s", (student_id,))
    current = cur.fetchone()[0]
    cur.execute("UPDATE students SET is_active = %s WHERE id = %s", (not bool(current), student_id))
    conn.commit()
    cur.close()
    conn.close()
    flash("Student account status updated.", "success")
    return redirect(url_for('admin.accounts'))


@admin_bp.route('/accounts/staff/<int:staff_id>/toggle', methods=['POST'])
@admin_required
def toggle_staff_account(staff_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT is_active FROM staff WHERE id = %s", (staff_id,))
    current = cur.fetchone()[0]
    cur.execute("UPDATE staff SET is_active = %s WHERE id = %s", (not bool(current), staff_id))
    conn.commit()
    cur.close()
    conn.close()
    flash("Staff account status updated.", "success")
    return redirect(url_for('admin.accounts'))


# ============================================================
# RESULT REVIEW / PUBLISH RESULTS (dedicated pages — separate
# from the Scrutinize workflow above; both operate on the same
# enrollments table)
# ============================================================
@admin_bp.route('/results/pending')
@admin_required
def pending_results():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT e.id AS enrollment_id, e.marks_obtained, e.exam_attendance,
               e.submitted_at, st.name AS student_name, st.student_id AS student_code,
               c.course_code, c.course_name, sem.id AS semester_id, sem.name AS semester_name,
               fac.name AS submitted_by_name
        FROM enrollments e
        JOIN students st ON e.student_id = st.id
        JOIN course_offerings co ON e.course_offering_id = co.id
        JOIN courses c ON co.course_id = c.id
        JOIN semesters sem ON co.semester_id = sem.id
        LEFT JOIN staff fac ON e.submitted_by = fac.id
        WHERE e.submission_status = 'submitted_by_faculty'
        ORDER BY sem.id DESC, c.course_code, st.name
    """)
    rows = cur.fetchall()
    for row in rows:
        row['preview_grade'] = marks_to_grade(row['marks_obtained']) if row['exam_attendance'] == 'present' else 'F'
    cur.close()
    conn.close()
    return render_template('admin/results_pending.html', rows=rows)


@admin_bp.route('/results/<int:enrollment_id>/approve', methods=['POST'])
@admin_required
def approve_result(enrollment_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    admin_id = session['user_id']

    cur.execute("SELECT id, marks_obtained, exam_attendance, submission_status FROM enrollments WHERE id = %s", (enrollment_id,))
    enrollment = cur.fetchone()
    if not enrollment or enrollment['submission_status'] != 'submitted_by_faculty':
        flash("This result is not awaiting review.", "error")
        cur.close(); conn.close()
        return redirect(url_for('admin.pending_results'))

    grade = marks_to_grade(enrollment['marks_obtained']) if enrollment['exam_attendance'] == 'present' else 'F'
    credit_completed, is_supplementary = determine_completion(grade, enrollment['exam_attendance'])

    cur.execute("""
        UPDATE enrollments
        SET grade = %s, grade_point = %s, credit_completed = %s, is_supplementary = %s,
            submission_status = 'approved_by_admin', approved_by = %s, approved_at = NOW(), admin_remarks = NULL
        WHERE id = %s
    """, (grade, get_grade_point(grade), credit_completed, is_supplementary, admin_id, enrollment_id))
    conn.commit()
    cur.close()
    conn.close()
    flash(f"Result approved ({grade}).", "success")
    return redirect(url_for('admin.pending_results'))


@admin_bp.route('/results/<int:enrollment_id>/reject', methods=['POST'])
@admin_required
def reject_result(enrollment_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash("Please provide a reason for rejecting this result.", "error")
        return redirect(url_for('admin.pending_results'))

    cur.execute("SELECT id, submission_status FROM enrollments WHERE id = %s", (enrollment_id,))
    enrollment = cur.fetchone()
    if not enrollment or enrollment['submission_status'] != 'submitted_by_faculty':
        flash("This result is not awaiting review.", "error")
        cur.close(); conn.close()
        return redirect(url_for('admin.pending_results'))

    cur.execute("""
        UPDATE enrollments SET marks_obtained = NULL, grade = NULL, submission_status = 'not_submitted', admin_remarks = %s
        WHERE id = %s
    """, (reason, enrollment_id))
    conn.commit()
    cur.close()
    conn.close()
    flash("Result rejected and sent back to faculty for resubmission.", "success")
    return redirect(url_for('admin.pending_results'))


@admin_bp.route('/results/approved')
@admin_required
def approved_results():
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT sem.id AS semester_id, sem.name AS semester_name, sem.result_published,
               SUM(CASE WHEN e.submission_status = 'approved_by_admin' THEN 1 ELSE 0 END) AS ready_count,
               SUM(CASE WHEN e.submission_status IN ('not_submitted', 'submitted_by_faculty') THEN 1 ELSE 0 END) AS blocking_count
        FROM enrollments e
        JOIN course_offerings co ON e.course_offering_id = co.id
        JOIN semesters sem ON co.semester_id = sem.id
        GROUP BY sem.id, sem.name, sem.result_published
        HAVING ready_count > 0 OR blocking_count > 0
        ORDER BY sem.id DESC
    """)
    semester_summaries = cur.fetchall()

    semester_id = request.args.get('semester_id', type=int)
    detail_rows = []
    if semester_id:
        cur.execute("""
            SELECT e.id AS enrollment_id, e.marks_obtained, e.grade, e.exam_attendance,
                   e.is_supplementary, e.credit_completed, e.approved_at,
                   st.name AS student_name, st.student_id AS student_code,
                   c.course_code, c.course_name
            FROM enrollments e
            JOIN students st ON e.student_id = st.id
            JOIN course_offerings co ON e.course_offering_id = co.id
            JOIN courses c ON co.course_id = c.id
            WHERE co.semester_id = %s AND e.submission_status = 'approved_by_admin'
            ORDER BY c.course_code, st.name
        """, (semester_id,))
        detail_rows = cur.fetchall()

    cur.close()
    conn.close()
    return render_template(
        'admin/results_approved.html',
        semester_summaries=semester_summaries, detail_rows=detail_rows, selected_semester_id=semester_id,
    )


@admin_bp.route('/results/publish/<int:semester_id>', methods=['POST'])
@admin_required
def publish_results(semester_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT id, name FROM semesters WHERE id = %s", (semester_id,))
    semester = cur.fetchone()
    if not semester:
        flash("Semester not found.", "error")
        cur.close(); conn.close()
        return redirect(url_for('admin.approved_results'))

    cur.execute("""
        SELECT COUNT(*) AS blocking_count FROM enrollments e
        JOIN course_offerings co ON e.course_offering_id = co.id
        WHERE co.semester_id = %s AND e.submission_status IN ('not_submitted', 'submitted_by_faculty')
    """, (semester_id,))
    blocking = cur.fetchone()['blocking_count']

    if blocking > 0:
        flash(f"Cannot publish {semester['name']}: {blocking} result(s) still unsubmitted or awaiting review.", "error")
        cur.close(); conn.close()
        return redirect(url_for('admin.approved_results', semester_id=semester_id))

    cur.execute("""
        UPDATE enrollments e
        JOIN course_offerings co ON e.course_offering_id = co.id
        SET e.submission_status = 'published'
        WHERE co.semester_id = %s AND e.submission_status = 'approved_by_admin'
    """, (semester_id,))
    published_count = cur.rowcount

    cur.execute("UPDATE semesters SET result_published = TRUE, result_publish_date = NOW() WHERE id = %s", (semester_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash(f"{semester['name']} results published — {published_count} record(s) now visible to students.", "success")
    return redirect(url_for('admin.approved_results'))