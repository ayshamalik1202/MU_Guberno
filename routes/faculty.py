"""
routes/faculty.py
Faculty panel — view assigned course offerings and submit student results.

Submitted results never touch the student-visible side directly: submitting
here only sets submission_status = 'submitted_by_faculty'. Nothing becomes
visible to a student until admin approves (routes/admin.py) AND the semester
is published. A faculty member can only submit for course offerings they are
actually assigned to (co.faculty_id check on every route).
"""

from functools import wraps
from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from database import get_db
from werkzeug.security import generate_password_hash, check_password_hash

faculty_bp = Blueprint('faculty', __name__, url_prefix='/faculty')


# ------------------------------------------------------------------
# Access control: only logged-in faculty
# ------------------------------------------------------------------
def faculty_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get('role') != 'faculty' or 'user_id' not in session:
            flash("Please sign in as faculty to continue.", "error")
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return wrapper


def _get_owned_offering(cur, offering_id, faculty_id):
    """Fetch a course offering only if it belongs to this faculty member."""
    cur.execute("""
        SELECT co.id, co.class_time, co.room, co.semester_id,
               c.course_code, c.course_name, sem.name AS semester_name
        FROM course_offerings co
        JOIN courses c ON co.course_id = c.id
        JOIN semesters sem ON co.semester_id = sem.id
        WHERE co.id = %s AND co.faculty_id = %s
    """, (offering_id, faculty_id))
    return cur.fetchone()


# ------------------------------------------------------------------
# DASHBOARD — list of assigned course offerings + submission progress
# ------------------------------------------------------------------
@faculty_bp.route('/dashboard')
@faculty_required
def dashboard():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    faculty_id = session['user_id']

    cur.execute("SELECT * FROM staff WHERE id = %s", (faculty_id,))
    faculty = cur.fetchone()

    cur.execute("""
        SELECT co.id AS offering_id, co.class_time, co.room,
               c.course_code, c.course_name, sem.name AS semester_name,
               sem.is_current,
               COUNT(e.id) AS total_students,
               SUM(CASE WHEN e.submission_status = 'not_submitted' THEN 1 ELSE 0 END) AS ungraded_count,
               SUM(CASE WHEN e.submission_status IN ('submitted_by_faculty', 'approved_by_admin', 'published')
                        THEN 1 ELSE 0 END) AS graded_count
        FROM course_offerings co
        JOIN courses c ON co.course_id = c.id
        JOIN semesters sem ON co.semester_id = sem.id
        LEFT JOIN enrollments e ON e.course_offering_id = co.id
        WHERE co.faculty_id = %s
        GROUP BY co.id, co.class_time, co.room, c.course_code, c.course_name,
                 sem.name, sem.is_current
        ORDER BY sem.is_current DESC, c.course_code
    """, (faculty_id,))
    offerings = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('faculty/dashboard.html', faculty=faculty, offerings=offerings)


# ------------------------------------------------------------------
# ROUTINE — view class schedule for assigned course offerings
# ------------------------------------------------------------------
@faculty_bp.route('/routine')
@faculty_required
def routine():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    faculty_id = session['user_id']

    cur.execute("SELECT * FROM staff WHERE id = %s", (faculty_id,))
    faculty = cur.fetchone()

    cur.execute("""
        SELECT co.class_time, co.room,
               c.course_code, c.course_name, sem.name AS semester_name
        FROM course_offerings co
        JOIN courses c ON co.course_id = c.id
        JOIN semesters sem ON co.semester_id = sem.id
        WHERE co.faculty_id = %s AND sem.is_current = 1
        ORDER BY co.class_time
    """, (faculty_id,))
    routines = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('faculty/routine.html', faculty=faculty, routines=routines)


# ------------------------------------------------------------------
# PROFILE — view faculty member account details
# ------------------------------------------------------------------
@faculty_bp.route('/profile')
@faculty_required
def profile():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    faculty_id = session['user_id']

    cur.execute("SELECT * FROM staff WHERE id = %s", (faculty_id,))
    faculty = cur.fetchone()

    cur.close()
    conn.close()

    return render_template('faculty/profile.html', faculty=faculty)


# ------------------------------------------------------------------
# PROFILE — update email (must stay @metrouni.edu.bd)
# ------------------------------------------------------------------
@faculty_bp.route('/profile/update-email', methods=['POST'])
@faculty_required
def update_email():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    faculty_id = session['user_id']

    new_email = request.form.get('new_email', '').strip().lower()

    if not new_email.endswith('@metrouni.edu.bd'):
        flash("Email must end with @metrouni.edu.bd.", "error")
        cur.close(); conn.close()
        return redirect(url_for('faculty.profile'))

    try:
        cur.execute("UPDATE staff SET email = %s WHERE id = %s", (new_email, faculty_id))
        conn.commit()
        session['email'] = new_email
        flash("Email updated successfully.", "success")
    except Exception as err:
        conn.rollback()
        if '1062' in str(err):
            flash("That email is already in use by another account.", "error")
        else:
            flash(f"Error updating email: {err}", "error")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('faculty.profile'))


# ------------------------------------------------------------------
# PROFILE — update password (requires current password)
# ------------------------------------------------------------------
@faculty_bp.route('/profile/update-password', methods=['POST'])
@faculty_required
def update_password():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    faculty_id = session['user_id']

    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    cur.execute("SELECT password FROM staff WHERE id = %s", (faculty_id,))
    row = cur.fetchone()

    if not row or not check_password_hash(row['password'], current_password):
        flash("Current password is incorrect.", "error")
        cur.close(); conn.close()
        return redirect(url_for('faculty.profile'))

    if len(new_password) < 8:
        flash("New password must be at least 8 characters.", "error")
        cur.close(); conn.close()
        return redirect(url_for('faculty.profile'))

    if new_password != confirm_password:
        flash("New password and confirmation do not match.", "error")
        cur.close(); conn.close()
        return redirect(url_for('faculty.profile'))

    hashed = generate_password_hash(new_password)
    cur.execute("UPDATE staff SET password = %s WHERE id = %s", (hashed, faculty_id))
    conn.commit()
    cur.close()
    conn.close()

    flash("Password updated successfully.", "success")
    return redirect(url_for('faculty.profile'))


# ------------------------------------------------------------------
# GRADES — view/enter marks for one course offering
# ------------------------------------------------------------------
@faculty_bp.route('/course-offering/<int:offering_id>/grades')
@faculty_required
def grades(offering_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    faculty_id = session['user_id']

    offering = _get_owned_offering(cur, offering_id, faculty_id)
    if not offering:
        flash("You are not assigned to that course offering.", "error")
        cur.close(); conn.close()
        return redirect(url_for('faculty.dashboard'))

    cur.execute("""
        SELECT e.id AS enrollment_id, e.marks_obtained, e.exam_attendance,
               e.submission_status, e.grade, e.admin_remarks,
               st.name AS student_name, st.student_id AS student_code
        FROM enrollments e
        JOIN students st ON e.student_id = st.id
        WHERE e.course_offering_id = %s
        ORDER BY st.name
    """, (offering_id,))
    roster_rows = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('faculty/grades.html', offering=offering, roster=roster_rows)


# ------------------------------------------------------------------
# SUBMIT — bulk-save marks for every editable row in the roster
# ------------------------------------------------------------------
@faculty_bp.route('/course-offering/<int:offering_id>/submit', methods=['POST'])
@faculty_required
def submit_results(offering_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    faculty_id = session['user_id']

    offering = _get_owned_offering(cur, offering_id, faculty_id)
    if not offering:
        flash("You are not assigned to that course offering.", "error")
        cur.close(); conn.close()
        return redirect(url_for('faculty.dashboard'))

    # Only rows still in 'not_submitted' are editable — everything else
    # (already submitted / approved / published) is locked from this side.
    cur.execute("""
        SELECT id FROM enrollments
        WHERE course_offering_id = %s AND submission_status = 'not_submitted'
    """, (offering_id,))
    editable_ids = {row['id'] for row in cur.fetchall()}

    if not editable_ids:
        flash("No editable results for this course — everything has already been submitted.", "error")
        cur.close(); conn.close()
        return redirect(url_for('faculty.grades', offering_id=offering_id))

    updated_count = 0
    skipped_invalid = 0

    for enrollment_id in editable_ids:
        marks_raw = request.form.get(f'marks_{enrollment_id}', '').strip()
        attendance = request.form.get(f'attendance_{enrollment_id}', 'present')

        if attendance not in ('present', 'absent'):
            attendance = 'present'

        if attendance == 'absent':
            marks = None
        else:
            if marks_raw == '':
                skipped_invalid += 1
                continue
            try:
                marks = float(marks_raw)
            except ValueError:
                skipped_invalid += 1
                continue
            if marks < 0 or marks > 100:
                skipped_invalid += 1
                continue

        cur.execute("""
            UPDATE enrollments
            SET marks_obtained = %s,
                exam_attendance = %s,
                submission_status = 'submitted_by_faculty',
                submitted_by = %s,
                submitted_at = NOW(),
                admin_remarks = NULL
            WHERE id = %s
        """, (marks, attendance, faculty_id, enrollment_id))
        updated_count += 1

    conn.commit()
    cur.close()
    conn.close()

    if skipped_invalid:
        flash(
            f"Submitted {updated_count} result(s). {skipped_invalid} row(s) were skipped "
            f"(missing or invalid marks) — enter those and submit again.", "error"
        )
    else:
        flash(f"Submitted {updated_count} result(s) for admin review.", "success")

    return redirect(url_for('faculty.grades', offering_id=offering_id))