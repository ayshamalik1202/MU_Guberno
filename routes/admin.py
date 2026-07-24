from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from database import get_db
import mysql.connector

admin_bp = Blueprint('admin', __name__)

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('Access denied. Admins only.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get counts for the admin overview cards
    cursor.execute("SELECT COUNT(*) as count FROM students")
    student_count = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM staff WHERE role = 'faculty'")
    faculty_count = cursor.fetchone()['count']
    
    # Fetch all pending service requests across the portal
    cursor.execute("""
        SELECT sr.*, s.name as student_name, s.student_id 
        FROM service_requests sr
        JOIN students s ON sr.student_id = s.id
        ORDER BY sr.created_at DESC
    """)
    requests = cursor.fetchall()
    
    cursor.close()
    db.close()
    return render_template('admin/dashboard.html', 
                           student_count=student_count, 
                           faculty_count=faculty_count, 
                           requests=requests)

@admin_bp.route('/request/<int:request_id>/update', methods=['POST'])
@admin_required
def update_request_status(request_id):
    status = request.form.get('status')
    db = get_db()
    cursor = db.cursor()
    
    try:
        cursor.execute("UPDATE service_requests SET status = %s WHERE id = %s", (status, request_id))
        db.commit()
        flash('Request status updated successfully!', 'success')
    except mysql.connector.Error as err:
        db.rollback()
        flash(f"Error: {err}", 'danger')
    finally:
        cursor.close()
        db.close()
        
    return redirect(url_for('admin.dashboard'))