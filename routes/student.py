from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from database import get_db  # Imports the get_db function from database.py

student_bp = Blueprint('student', __name__, url_prefix='/student')

# Helper function to check student login
def get_current_student_id():
    # Supports both 'user_id' and 'student_db_id' from session
    return session.get('user_id') or session.get('student_db_id')

# -------------------------------------------------------------------
# 1. DASHBOARD & CREDIT SUMMARY
# -------------------------------------------------------------------
@student_bp.route('/dashboard')
def dashboard():
    student_pk = get_current_student_id()
    if not student_pk:
        flash("Please sign in first.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # Fetch student profile details & GPA
    cursor.execute("SELECT * FROM students WHERE id = %s", (student_pk,))
    student = cursor.fetchone()

    # Calculate completed vs total enrolled courses
    cursor.execute("""
        SELECT 
            COUNT(CASE WHEN grade IS NOT NULL AND grade != 'F' THEN 1 END) AS completed_courses,
            COUNT(CASE WHEN grade IS NULL THEN 1 END) AS remaining_courses,
            COUNT(*) AS total_enrolled
        FROM enrollments 
        WHERE student_id = %s
    """, (student_pk,))
    summary = cursor.fetchone()

    # Check if student locked their profile via service_requests
    cursor.execute("""
        SELECT status FROM service_requests 
        WHERE student_id = %s AND service_type = 'Profile Lock' 
        ORDER BY id DESC LIMIT 1
    """, (student_pk,))
    lock_request = cursor.fetchone()
    is_locked = True if lock_request and lock_request['status'] == 'Approved' else False

    cursor.close()
    conn.close()

    return render_template('student/dashboard.html', 
                           student=student, 
                           summary=summary, 
                           is_locked=is_locked)

# -------------------------------------------------------------------
# 2. TRANSCRIPT (FULL ACADEMIC & COURSES)
# -------------------------------------------------------------------
@student_bp.route('/transcript')
def transcript():
    student_pk = get_current_student_id()
    if not student_pk:
        flash("Please sign in first.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # Retrieve all courses and assigned grades
    cursor.execute("""
        SELECT c.course_code, c.course_name, e.grade, s.name AS faculty_name
        FROM enrollments e
        JOIN courses c ON e.course_id = c.id
        LEFT JOIN staff s ON c.faculty_id = s.id
        WHERE e.student_id = %s
    """, (student_pk,))
    grades = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('student/transcript.html', grades=grades)

# -------------------------------------------------------------------
# 3. COMPLAIN & SERVICE REQUEST BOX (4 Categorized Options)
# -------------------------------------------------------------------
COMPLAINT_TYPES = [
    'Dissatisfaction of Result',
    'Payment Issue or Receipt Issue',
    'Account Back or Access Issue',
    'Others'
]

@student_bp.route('/complaints', methods=['GET', 'POST'])
def complaints():
    student_pk = get_current_student_id()
    if not student_pk:
        flash("Please sign in first.", "danger")
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        category = request.form.get('category')
        description = request.form.get('description')

        if category in COMPLAINT_TYPES and description:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO service_requests (student_id, service_type, details, status)
                VALUES (%s, %s, %s, 'Pending')
            """, (student_pk, category, description))
            conn.commit()
            cursor.close()
            conn.close()

            flash("Your complaint/request has been submitted to the admin.", "success")
            return redirect(url_for('student.complaints'))

    # Fetch previous complaints/requests status
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT * FROM service_requests 
        WHERE student_id = %s 
        ORDER BY created_at DESC
    """, (student_pk,))
    my_requests = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('student/complaints.html', 
                           categories=COMPLAINT_TYPES, 
                           requests=my_requests)

# -------------------------------------------------------------------
# 4. COURSE & FACULTY LIST WITH SCHEDULE
# -------------------------------------------------------------------
@student_bp.route('/courses')
def courses():
    student_pk = get_current_student_id()
    if not student_pk:
        flash("Please sign in first.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # Fetch registered courses along with instructor names
    cursor.execute("""
        SELECT c.course_code, c.course_name, s.name AS faculty_name, s.email AS faculty_email
        FROM enrollments e
        JOIN courses c ON e.course_id = c.id
        LEFT JOIN staff s ON c.faculty_id = s.id
        WHERE e.student_id = %s
    """, (student_pk,))
    enrolled_courses = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('student/courses.html', courses=enrolled_courses)

# -------------------------------------------------------------------
# 5. SEMESTER FEE PAYMENTS & RECEIPT LOG
# -------------------------------------------------------------------
@student_bp.route('/payment', methods=['GET', 'POST'])
def payment():
    student_pk = get_current_student_id()
    if not student_pk:
        flash("Please sign in first.", "danger")
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        method = request.form.get('payment_method') # Mobile or Online Banking
        tx_id = request.form.get('transaction_id')
        amount = request.form.get('amount')

        payment_details = f"Method: {method} | TxID: {tx_id} | Amount: {amount} BDT"

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO service_requests (student_id, service_type, details, status)
            VALUES (%s, 'Semester Fee Payment', %s, 'Pending')
        """, (student_pk, payment_details))
        conn.commit()
        cursor.close()
        conn.close()

        flash("Payment submitted! The admin will verify and release your receipt shortly.", "info")
        return redirect(url_for('student.payment'))

    return render_template('student/payment.html')