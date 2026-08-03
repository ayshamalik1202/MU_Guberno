"""
Student panel: dashboard, transcript, course/credit tracking,
semester registration, fee payments, and complaints.

All result data only ever shows rows where submission_status = 'published' —
faculty-submitted and admin-approved-but-unpublished results are NEVER
visible to the student. This is enforced at the query level, not just in
the template, so there's no way to leak an unpublished result by mistake.
"""

from functools import wraps
from datetime import datetime
from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from database import get_db
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.gpa_calculator import calculate_cgpa

student_bp = Blueprint('student', __name__)


# ------------------------------------------------------------------
# Access control: only logged-in students can hit these routes
# ------------------------------------------------------------------
def student_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get('role') != 'student' or 'user_id' not in session:
            flash("Please sign in as a student to continue.", "error")
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return wrapper


# ------------------------------------------------------------------
# DASHBOARD (overview + courses/credits + registration + payments)
# ------------------------------------------------------------------
@student_bp.route('/dashboard')
@student_required
def dashboard():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    student_id = session['user_id']

    # --- Basic profile ---
    cur.execute("SELECT * FROM students WHERE id = %s", (student_id,))
    student = cur.fetchone()

    # --- CGPA + credits completed (only from PUBLISHED results, including 'F' grades for CGPA math) ---
    cur.execute("""
        SELECT crc.credits, e.grade
        FROM enrollments e
        JOIN course_offerings co ON e.course_offering_id = co.id
        JOIN courses c ON co.course_id = c.id
        JOIN curriculum crc ON crc.course_id = c.id
        WHERE e.student_id = %s
          AND e.submission_status = 'published'
    """, (student_id,))
    completed_rows = cur.fetchall()

    # Calculation offloaded directly to utils/gpa_calculator.py
    cgpa, total_credits_completed = calculate_cgpa(completed_rows)

    # --- Total credits required by curriculum ---
    cur.execute("SELECT COALESCE(SUM(credits), 0) AS total FROM curriculum")
    total_required = float(cur.fetchone()['total'] or 0)
    credits_remaining = max(total_required - total_credits_completed, 0)

    # --- Full curriculum with per-student completion status, grouped by
    #     program semester_level (1.1, 1.2, ... 4.3) ---
    cur.execute("""
        SELECT c.id AS course_id, c.course_code, c.course_name, crc.credits, crc.semester_level,
               COALESCE(MAX(e.credit_completed), 0) AS credit_completed,
               MAX(e.is_supplementary) AS is_supplementary,
               MAX(CASE e.submission_status
                       WHEN 'not_submitted'        THEN 1
                       WHEN 'submitted_by_faculty'  THEN 2
                       WHEN 'approved_by_admin'     THEN 3
                       WHEN 'published'             THEN 4
                       ELSE 0
                   END) AS status_rank
        FROM curriculum crc
        JOIN courses c ON crc.course_id = c.id
        LEFT JOIN course_offerings co ON co.course_id = c.id
        LEFT JOIN enrollments e
               ON e.course_offering_id = co.id AND e.student_id = %s
        GROUP BY c.id, c.course_code, c.course_name, crc.credits, crc.semester_level
        ORDER BY crc.semester_level, c.course_code
    """, (student_id,))
    curriculum_rows = cur.fetchall()

    status_by_rank = {
        0: None,
        1: 'not_submitted',
        2: 'submitted_by_faculty',
        3: 'approved_by_admin',
        4: 'published',
    }
    for row in curriculum_rows:
        row['submission_status'] = status_by_rank.get(row.pop('status_rank'), None)

    # --- Current semester registration (courses, faculty, class time) ---
    cur.execute("""
        SELECT c.course_code, c.course_name, s.name AS faculty_name,
               co.class_time, co.room
        FROM enrollments e
        JOIN course_offerings co ON e.course_offering_id = co.id
        JOIN courses c ON co.course_id = c.id
        JOIN semesters sem ON co.semester_id = sem.id
        LEFT JOIN staff s ON co.faculty_id = s.id
        WHERE e.student_id = %s AND sem.is_current = TRUE
        ORDER BY c.course_code
    """, (student_id,))
    registered_courses = cur.fetchall()

    # --- Current semester + payment status (per-student fee, from student_fees) ---
    cur.execute("SELECT * FROM semesters WHERE is_current = TRUE LIMIT 1")
    current_semester = cur.fetchone()

    payment_due = None
    if current_semester:
        cur.execute("""
            SELECT amount_due FROM student_fees
            WHERE student_id = %s AND semester_id = %s
        """, (student_id, current_semester['id']))
        fee_row = cur.fetchone()

        if fee_row:
            cur.execute("""
                SELECT * FROM payments
                WHERE student_id = %s AND semester_id = %s
                ORDER BY submitted_at DESC LIMIT 1
            """, (student_id, current_semester['id']))
            latest_payment = cur.fetchone()
            if not latest_payment or latest_payment['status'] != 'verified':
                payment_due = fee_row['amount_due']

    # --- Payment history (own payments only) ---
    cur.execute("""
        SELECT p.*, sem.name AS semester_name
        FROM payments p
        JOIN semesters sem ON p.semester_id = sem.id
        WHERE p.student_id = %s
        ORDER BY p.submitted_at DESC
    """, (student_id,))
    payment_history = cur.fetchall()

    # --- Notifications: newly published results + payment reminders ---
    notifications = []
    cur.execute("""
        SELECT DISTINCT sem.name, sem.result_publish_date
        FROM enrollments e
        JOIN course_offerings co ON e.course_offering_id = co.id
        JOIN semesters sem ON co.semester_id = sem.id
        WHERE e.student_id = %s AND e.submission_status = 'published'
          AND sem.result_published = TRUE
        ORDER BY sem.result_publish_date DESC LIMIT 1
    """, (student_id,))
    latest_result = cur.fetchone()
    if latest_result:
        notifications.append(f"{latest_result['name']} result has been published.")
    if payment_due:
        notifications.append(f"Semester fee of {payment_due} is due.")

    cur.close()
    conn.close()

    return render_template(
        'student/dashboard.html',
        student=student,
        cgpa=cgpa,
        credits_completed=total_credits_completed,
        credits_remaining=credits_remaining,
        total_required=total_required,
        curriculum=curriculum_rows,
        registered_courses=registered_courses,
        current_semester=current_semester,
        payment_due=payment_due,
        payment_history=payment_history,
        notifications=notifications,
    )


# ------------------------------------------------------------------
# SEMESTER REGISTRATION — student self-enrolls into course offerings
# for the current semester (no SQL needed by admin/dev anymore)
# ------------------------------------------------------------------
@student_bp.route('/register', methods=['GET', 'POST'])
@student_required
def register():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    student_id = session['user_id']

    cur.execute("SELECT * FROM semesters WHERE is_current = TRUE LIMIT 1")
    current_semester = cur.fetchone()

    if not current_semester:
        flash("No active semester is open for registration right now.", "error")
        cur.close(); conn.close()
        return redirect(url_for('student.dashboard'))

    if request.method == 'POST':
        offering_id = request.form.get('offering_id', type=int)

        if not offering_id:
            flash("Please select a course to register.", "error")
        else:
            # Confirm the offering belongs to the current semester
            cur.execute("""
                SELECT id FROM course_offerings
                WHERE id = %s AND semester_id = %s
            """, (offering_id, current_semester['id']))
            offering = cur.fetchone()

            if not offering:
                flash("Invalid course offering.", "error")
            else:
                try:
                    cur.execute("""
                        INSERT INTO enrollments (student_id, course_offering_id)
                        VALUES (%s, %s)
                    """, (student_id, offering_id))
                    conn.commit()
                    flash("Successfully registered for the course.", "success")
                except Exception as err:
                    conn.rollback()
                    if 'unique_enrollment' in str(err) or '1062' in str(err):
                        flash("You are already registered for this course.", "error")
                    else:
                        flash(f"Registration error: {err}", "error")

    # Courses already registered for this semester (to mark them)
    cur.execute("""
        SELECT co.id AS offering_id
        FROM enrollments e
        JOIN course_offerings co ON e.course_offering_id = co.id
        WHERE e.student_id = %s AND co.semester_id = %s
    """, (student_id, current_semester['id']))
    already_registered = {row['offering_id'] for row in cur.fetchall()}

    # All course offerings available this semester
    cur.execute("""
        SELECT co.id AS offering_id, c.course_code, c.course_name,
               d.short_form AS department, st.name AS faculty_name,
               co.class_time, co.room
        FROM course_offerings co
        JOIN courses c ON co.course_id = c.id
        LEFT JOIN departments d ON c.department_id = d.id
        LEFT JOIN staff st ON co.faculty_id = st.id
        WHERE co.semester_id = %s
        ORDER BY d.short_form, c.course_code
    """, (current_semester['id'],))
    offerings = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        'student/register.html',
        current_semester=current_semester,
        offerings=offerings,
        already_registered=already_registered,
    )


# ------------------------------------------------------------------
# TRANSCRIPT (full or semester-wise) — PUBLISHED results only
# ------------------------------------------------------------------
@student_bp.route('/transcript')
@student_required
def transcript():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    student_id = session['user_id']

    view = request.args.get('view', 'full')
    semester_id = request.args.get('semester_id', type=int)

    query = """
        SELECT e.id AS enrollment_id, c.course_code, c.course_name, crc.credits, e.grade,
               e.is_supplementary, e.exam_attendance, sem.id AS semester_id,
               sem.name AS semester_name
        FROM enrollments e
        JOIN course_offerings co ON e.course_offering_id = co.id
        JOIN courses c ON co.course_id = c.id
        LEFT JOIN curriculum crc ON crc.course_id = c.id
        JOIN semesters sem ON co.semester_id = sem.id
        WHERE e.student_id = %s AND e.submission_status = 'published'
    """
    params = [student_id]

    if view == 'semester' and semester_id:
        query += " AND sem.id = %s"
        params.append(semester_id)

    query += " ORDER BY sem.id, c.course_code"
    cur.execute(query, tuple(params))
    transcript_rows = cur.fetchall()
    # ...rest unchanged

    # Semester list for the dropdown (only semesters with published results)
    cur.execute("""
        SELECT DISTINCT sem.id, sem.name
        FROM semesters sem
        JOIN course_offerings co ON co.semester_id = sem.id
        JOIN enrollments e ON e.course_offering_id = co.id
        WHERE e.student_id = %s AND e.submission_status = 'published'
        ORDER BY sem.id DESC
    """, (student_id,))
    semesters = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        'student/transcript.html',
        transcript_rows=transcript_rows,
        semesters=semesters,
        view=view,
        selected_semester_id=semester_id,
    )


# ------------------------------------------------------------------
# PAYMENTS — student submits a claim; admin verifies it separately.
# Amount is looked up from student_fees (per-student, per-semester),
# not a flat semester-wide fee.
# ------------------------------------------------------------------
@student_bp.route('/payments/pay', methods=['POST'])
@student_required
def pay():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    student_id = session['user_id']

    method = request.form.get('pay_method')
    account_ref = request.form.get('account_reference', '').strip()

    if method not in ('mobile_banking', 'online_banking') or not account_ref:
        flash("Please provide a valid payment method and account reference.", "error")
        return redirect(url_for('student.dashboard'))

    cur.execute("SELECT * FROM semesters WHERE is_current = TRUE LIMIT 1")
    current_semester = cur.fetchone()
    if not current_semester:
        flash("No active semester found for payment.", "error")
        return redirect(url_for('student.dashboard'))

    cur.execute("""
        SELECT amount_due FROM student_fees
        WHERE student_id = %s AND semester_id = %s
    """, (student_id, current_semester['id']))
    fee_row = cur.fetchone()

    if not fee_row:
        flash("No fee has been assigned to you for this semester yet. Contact admin.", "error")
        cur.close(); conn.close()
        return redirect(url_for('student.dashboard'))

    cur.execute("""
        INSERT INTO payments (student_id, semester_id, amount, method, account_reference, status)
        VALUES (%s, %s, %s, %s, %s, 'pending')
    """, (student_id, current_semester['id'], fee_row['amount_due'], method, account_ref))
    conn.commit()
    cur.close()
    conn.close()

    flash("Payment submitted. It is pending admin verification — your receipt will be available once verified.", "success")
    return redirect(url_for('student.dashboard'))


# ------------------------------------------------------------------
# COMPLAINTS (general — payment/access/other, not tied to a specific result)
# ------------------------------------------------------------------
@student_bp.route('/complaints', methods=['GET', 'POST'])
@student_required
def complaints():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    student_id = session['user_id']

    if request.method == 'POST':
        category = request.form.get('category')
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()

        valid_categories = ('result', 'payment', 'access', 'other')
        if category not in valid_categories or not subject or not message:
            flash("Please fill in all complaint fields correctly.", "error")
        else:
            cur.execute("""
                INSERT INTO complaints (student_id, category, subject, message)
                VALUES (%s, %s, %s, %s)
            """, (student_id, category, subject, message))
            conn.commit()
            flash("Complaint submitted. The admin team will review it shortly.", "success")

    cur.execute("""
        SELECT * FROM complaints
        WHERE student_id = %s
        ORDER BY created_at DESC
    """, (student_id,))
    complaint_history = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('student/complaints.html', complaints=complaint_history)


# ------------------------------------------------------------------
# RESULT COMPLAINT — student disputes a specific published grade.
# Feeds result_complaints, which admin.dashboard() already reads and
# admin.knock_faculty() already knows how to forward back to faculty.
# ------------------------------------------------------------------
@student_bp.route('/result/<int:enrollment_id>/complain', methods=['POST'])
@student_required
def complain_about_result(enrollment_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    student_id = session['user_id']

    reason = request.form.get('reason', '').strip()
    if not reason:
        flash("Please describe the issue with this result.", "error")
        return redirect(url_for('student.transcript'))

    # Only allow a complaint on a result that's actually published and
    # belongs to this student.
    cur.execute("""
        SELECT e.id FROM enrollments e
        WHERE e.id = %s AND e.student_id = %s AND e.submission_status = 'published'
    """, (enrollment_id, student_id))
    enrollment = cur.fetchone()

    if not enrollment:
        flash("You can only raise a complaint on a published result.", "error")
        cur.close(); conn.close()
        return redirect(url_for('student.transcript'))

    # Prevent duplicate open complaints on the same result
    cur.execute("""
        SELECT id FROM result_complaints
        WHERE enrollment_id = %s AND status IN ('pending', 'sent_to_faculty')
    """, (enrollment_id,))
    if cur.fetchone():
        flash("You already have an open complaint for this result.", "error")
        cur.close(); conn.close()
        return redirect(url_for('student.transcript'))

    cur.execute("""
        INSERT INTO result_complaints (enrollment_id, reason)
        VALUES (%s, %s)
    """, (enrollment_id, reason))
    conn.commit()
    cur.close()
    conn.close()

    flash("Complaint submitted — admin will review and may forward it to your instructor.", "success")
    return redirect(url_for('student.transcript'))


# ------------------------------------------------------------------
# PROFILE PRIVACY LOCK
# ------------------------------------------------------------------
@student_bp.route('/profile/privacy', methods=['POST'])
@student_required
def toggle_privacy():
    conn = get_db()
    cur = conn.cursor()
    student_id = session['user_id']

    cur.execute("SELECT profile_locked FROM students WHERE id = %s", (student_id,))
    row = cur.fetchone()
    current = row['profile_locked'] if isinstance(row, dict) else row[0]
    new_value = not bool(current)

    cur.execute("UPDATE students SET profile_locked = %s WHERE id = %s", (new_value, student_id))
    conn.commit()
    cur.close()
    conn.close()

    flash("Profile locked." if new_value else "Profile unlocked.", "success")
    return redirect(url_for('student.dashboard'))