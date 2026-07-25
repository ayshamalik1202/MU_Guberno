"""
routes/admin.py
Admin panel — result review/approval pipeline.

Workflow enforced here:
    faculty submits marks  ->  submission_status = 'submitted_by_faculty'
    admin reviews + approves  ->  submission_status = 'approved_by_admin'
        (grade, credit_completed, is_supplementary all computed here,
         from marks_obtained + exam_attendance — never trusted from faculty input)
    admin rejects  ->  submission_status = 'not_submitted', marks/grade cleared,
        admin_remarks holds the reason, faculty resubmits
    admin publishes a semester  ->  every 'approved_by_admin' row for that
        semester flips to 'published' in one transaction, and the semester's
        result_published / result_publish_date are set — this is the single
        moment students' dashboards/transcripts/notifications light up.
"""

from functools import wraps
from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from database import get_db
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.gpa_calculator import marks_to_grade, determine_completion

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


# ------------------------------------------------------------------
# Access control: only logged-in, active admins
# ------------------------------------------------------------------
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get('role') != 'admin' or 'user_id' not in session:
            flash("Please sign in as an admin to continue.", "error")
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return wrapper


# ------------------------------------------------------------------
# DASHBOARD — overview stats
# ------------------------------------------------------------------
@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT * FROM staff WHERE id = %s", (session['user_id'],))
    admin = cur.fetchone()

    cur.execute("SELECT COUNT(*) AS c FROM enrollments WHERE submission_status = 'submitted_by_faculty'")
    pending_review_count = cur.fetchone()['c']

    cur.execute("SELECT COUNT(*) AS c FROM enrollments WHERE submission_status = 'approved_by_admin'")
    ready_to_publish_count = cur.fetchone()['c']

    cur.execute("SELECT COUNT(*) AS c FROM students")
    total_students = cur.fetchone()['c']

    cur.execute("SELECT COUNT(*) AS c FROM staff WHERE role = 'faculty'")
    total_faculty = cur.fetchone()['c']

    cur.execute("""
        SELECT e.id AS enrollment_id, st.name AS student_name,
               c.course_code, e.submitted_at
        FROM enrollments e
        JOIN students st ON e.student_id = st.id
        JOIN course_offerings co ON e.course_offering_id = co.id
        JOIN courses c ON co.course_id = c.id
        WHERE e.submission_status = 'submitted_by_faculty'
        ORDER BY e.submitted_at DESC LIMIT 5
    """)
    recent_pending = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        'admin/dashboard.html',
        admin=admin,
        pending_review_count=pending_review_count,
        ready_to_publish_count=ready_to_publish_count,
        total_students=total_students,
        total_faculty=total_faculty,
        recent_pending=recent_pending,
    )


# ------------------------------------------------------------------
# RESULTS AWAITING REVIEW (submitted by faculty, not yet approved)
# ------------------------------------------------------------------
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

    # Preview the grade each row WOULD get if approved as-is, so the admin
    # can sanity-check before clicking approve.
    for row in rows:
        row['preview_grade'] = marks_to_grade(row['marks_obtained']) \
            if row['exam_attendance'] == 'present' else 'F'

    cur.close()
    conn.close()

    return render_template('admin/results_pending.html', rows=rows)


# ------------------------------------------------------------------
# APPROVE a single submitted result
# ------------------------------------------------------------------
@admin_bp.route('/results/<int:enrollment_id>/approve', methods=['POST'])
@admin_required
def approve_result(enrollment_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    admin_id = session['user_id']

    cur.execute("""
        SELECT id, marks_obtained, exam_attendance, submission_status
        FROM enrollments WHERE id = %s
    """, (enrollment_id,))
    enrollment = cur.fetchone()

    if not enrollment:
        flash("Enrollment record not found.", "error")
        cur.close(); conn.close()
        return redirect(url_for('admin.pending_results'))

    if enrollment['submission_status'] != 'submitted_by_faculty':
        flash("This result is not awaiting review (it may have already been processed).", "error")
        cur.close(); conn.close()
        return redirect(url_for('admin.pending_results'))

    grade = marks_to_grade(enrollment['marks_obtained']) \
        if enrollment['exam_attendance'] == 'present' else 'F'
    credit_completed, is_supplementary = determine_completion(grade, enrollment['exam_attendance'])

    cur.execute("""
        UPDATE enrollments
        SET grade = %s,
            credit_completed = %s,
            is_supplementary = %s,
            submission_status = 'approved_by_admin',
            approved_by = %s,
            approved_at = NOW(),
            admin_remarks = NULL
        WHERE id = %s
    """, (grade, credit_completed, is_supplementary, admin_id, enrollment_id))
    conn.commit()
    cur.close()
    conn.close()

    flash(f"Result approved ({grade}).", "success")
    return redirect(url_for('admin.pending_results'))


# ------------------------------------------------------------------
# REJECT a single submitted result (sends it back to faculty)
# ------------------------------------------------------------------
@admin_bp.route('/results/<int:enrollment_id>/reject', methods=['POST'])
@admin_required
def reject_result(enrollment_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    reason = request.form.get('reason', '').strip()
    if not reason:
        flash("Please provide a reason for rejecting this result.", "error")
        return redirect(url_for('admin.pending_results'))

    cur.execute("""
        SELECT id, submission_status FROM enrollments WHERE id = %s
    """, (enrollment_id,))
    enrollment = cur.fetchone()

    if not enrollment or enrollment['submission_status'] != 'submitted_by_faculty':
        flash("This result is not awaiting review.", "error")
        cur.close(); conn.close()
        return redirect(url_for('admin.pending_results'))

    cur.execute("""
        UPDATE enrollments
        SET marks_obtained = NULL,
            grade = NULL,
            submission_status = 'not_submitted',
            admin_remarks = %s
        WHERE id = %s
    """, (reason, enrollment_id))
    conn.commit()
    cur.close()
    conn.close()

    flash("Result rejected and sent back to faculty for resubmission.", "success")
    return redirect(url_for('admin.pending_results'))


# ------------------------------------------------------------------
# RESULTS APPROVED BUT NOT YET PUBLISHED — grouped by semester
# ------------------------------------------------------------------
@admin_bp.route('/results/approved')
@admin_required
def approved_results():
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    # Semester-level summary: how many approved-and-ready vs still-pending
    # rows exist, so admin can see at a glance which semesters are safe to publish.
    cur.execute("""
        SELECT sem.id AS semester_id, sem.name AS semester_name,
               sem.result_published,
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

    # Row-level detail for the currently-expanded semester, if requested
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
        semester_summaries=semester_summaries,
        detail_rows=detail_rows,
        selected_semester_id=semester_id,
    )


# ------------------------------------------------------------------
# PUBLISH all approved results for a semester (result day)
# ------------------------------------------------------------------
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

    # Safety check: refuse to publish if anything in this semester is still
    # unsubmitted or awaiting review — a partial publish would show some
    # students results while others silently see nothing, with no warning.
    cur.execute("""
        SELECT COUNT(*) AS blocking_count
        FROM enrollments e
        JOIN course_offerings co ON e.course_offering_id = co.id
        WHERE co.semester_id = %s
          AND e.submission_status IN ('not_submitted', 'submitted_by_faculty')
    """, (semester_id,))
    blocking = cur.fetchone()['blocking_count']

    if blocking > 0:
        flash(
            f"Cannot publish {semester['name']}: {blocking} result(s) are still "
            f"unsubmitted or awaiting admin review.", "error"
        )
        cur.close(); conn.close()
        return redirect(url_for('admin.approved_results', semester_id=semester_id))

    cur.execute("""
        UPDATE enrollments e
        JOIN course_offerings co ON e.course_offering_id = co.id
        SET e.submission_status = 'published'
        WHERE co.semester_id = %s AND e.submission_status = 'approved_by_admin'
    """, (semester_id,))
    published_count = cur.rowcount

    cur.execute("""
        UPDATE semesters
        SET result_published = TRUE, result_publish_date = NOW()
        WHERE id = %s
    """, (semester_id,))

    conn.commit()
    cur.close()
    conn.close()

    flash(f"{semester['name']} results published — {published_count} record(s) now visible to students.", "success")
    return redirect(url_for('admin.approved_results'))