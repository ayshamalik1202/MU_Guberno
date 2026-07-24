from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from database import get_db
import mysql.connector

faculty_bp = Blueprint('faculty', __name__)

def faculty_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'faculty':
            flash('Access denied. Faculty only.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@faculty_bp.route('/dashboard')
@faculty_required
def dashboard():
    faculty_id = session['user_id']
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Fetch assigned courses
    cursor.execute("SELECT * FROM courses WHERE faculty_id = %s", (faculty_id,))
    courses = cursor.fetchall()
    
    cursor.close()
    db.close()
    return render_template('faculty/dashboard.html', courses=courses)

@faculty_bp.route('/course/<int:course_id>/grades', methods=['GET', 'POST'])
@faculty_required
def manage_grades(course_id):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if request.method == 'POST':
        student_id = request.form.get('student_id')
        grade = request.form.get('grade')
        
        try:
            cursor.execute("""
                INSERT INTO enrollments (student_id, course_id, grade) 
                VALUES (%s, %s, %s) 
                ON DUPLICATE KEY UPDATE grade = %s
            """, (student_id, course_id, grade, grade))
            db.commit()
            flash('Grade updated successfully!', 'success')
        except mysql.connector.Error as err:
            db.rollback()
            flash(f"Error updating grade: {err}", 'danger')
            
    # Fetch students enrolled in this course
    cursor.execute("""
        SELECT s.id, s.name, s.student_id, e.grade 
        FROM students s
        JOIN enrollments e ON s.id = e.student_id
        WHERE e.course_id = %s
    """, (course_id,))
    students = cursor.fetchall()
    
    cursor.close()
    db.close()
    return render_template('faculty/grades.html', students=students, course_id=course_id)