"""
routes/student.py
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

    # --- Full curriculum with per-student completion status ---
    # NOTE: submission_status is a workflow ENUM ('not_submitted' -> 'submitted_by_faculty'
    # -> 'approved_by_admin' -> 'published'), so MAX() on the raw string is wrong: it compares
    # alphabetically ('submitted_by_faculty' > 'published'), which can hide a published result
    # behind a stale pending one from a retake. We rank each status numerically first, take the
    # MAX() of the rank, then map the winning rank back to its label.
    cur.execute("""
        SELECT c.id AS course_id, c.course_code, c.course_name, crc.credits,
               MAX(e.credit_completed) AS credit_completed,
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
        GROUP BY c.id, c.course_code, c.course_name, crc.credits
        ORDER BY c.course_code
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

    # --- Current semester + payment status ---
    cur.execute("SELECT * FROM semesters WHERE is_current = TRUE LIMIT 1")
    current_semester = cur.fetchone()

    payment_due = None
    if current_semester:
        cur.execute("""
            SELECT * FROM payments
            WHERE student_id = %s AND semester_id = %s
            ORDER BY submitted_at DESC LIMIT 1
        """, (student_id, current_semester['id']))
        latest_payment = cur.fetchone()
        if not latest_payment or latest_payment['status'] != 'verified':
            payment_due = current_semester['fee_amount']

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
    # NOTE: MySQL rejects `SELECT DISTINCT ... ORDER BY <col not in SELECT list>`
    # (error 3065: "incompatible with DISTINCT"). sem.result_publish_date must be
    # in the SELECT list for the ORDER BY to be valid.
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
# TRANSCRIPT (full or semester-wise) — PUBLISHED results only
# ------------------------------------------------------------------
@student_bp.route('/transcript')
@student_required
def transcript():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    student_id = session['user_id']

    view = request.args.get('view', 'full')          # 'full' or 'semester'
    semester_id = request.args.get('semester_id', type=int)

    query = """
        SELECT c.course_code, c.course_name, crc.credits, e.grade,
               e.is_supplementary, e.exam_attendance, sem.id AS semester_id,
               sem.name AS semester_name
        FROM enrollments e
        JOIN course_offerings co ON e.course_offering_id = co.id
        JOIN courses c ON co.course_id = c.id
        JOIN curriculum crc ON crc.course_id = c.id
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
# PAYMENTS — student submits a claim; admin verifies it separately
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
        INSERT INTO payments (student_id, semester_id, amount, method, account_reference, status)
        VALUES (%s, %s, %s, %s, %s, 'pending')
    """, (student_id, current_semester['id'], current_semester['fee_amount'], method, account_ref))
    conn.commit()
    cur.close()
    conn.close()

    flash("Payment submitted. It is pending admin verification — your receipt will be available once verified.", "success")
    return redirect(url_for('student.dashboard'))


# ------------------------------------------------------------------
# COMPLAINTS
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