from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from database import get_db
import mysql.connector

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        role = request.form.get('signup_role', 'student')
        name = request.form.get('name', '').strip()
        user_id = request.form.get('student_id', '').strip()  # Contains Student ID / Teacher ID / Admin ID
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        
        if password != confirm_password:
            flash('Passwords do not match!', 'danger')
            return render_template('login.html', signup_active=True)
            
        db = get_db()
        cursor = db.cursor()
        
        try:
            if role == 'student':
                # Insert into students table
                cursor.execute(
                    "INSERT INTO students (student_id, name, email, password) VALUES (%s, %s, %s, %s)", 
                    (user_id, name, email, password)
                )
            else:
                # Insert into staff table for 'faculty' or 'admin'
                cursor.execute(
                    "INSERT INTO staff (staff_id, name, email, password, role) VALUES (%s, %s, %s, %s, %s)", 
                    (user_id, name, email, password, role)
                )
                
            db.commit()
            flash('Account created successfully! Please sign in.', 'success')
            return redirect(url_for('auth.login'))
            
        except mysql.connector.Error as err:
            db.rollback()
            if err.errno == 1062:
                flash('An account with this ID or Email already exists. Please sign in.', 'danger')
            else:
                flash(f"Error creating account: {err}", 'danger')
            return render_template('login.html', signup_active=True)
        finally:
            cursor.close()
            db.close()
            
    return render_template('login.html', signup_active=True)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        role = request.form.get('role', 'student')
        
        db = get_db()
        cursor = db.cursor(dictionary=True)
        
        try:
            if role == 'student':
                cursor.execute("SELECT * FROM students WHERE LOWER(email) = %s AND password = %s", (email, password))
                user = cursor.fetchone()
                if user:
                    session['user_id'] = user['id']
                    session['role'] = 'student'
                    session['name'] = user['name']
                    return redirect(url_for('student.dashboard'))
            else:
                cursor.execute("SELECT * FROM staff WHERE LOWER(email) = %s AND password = %s AND role = %s", (email, password, role))
                user = cursor.fetchone()
                if user:
                    session['user_id'] = user['id']
                    session['role'] = user['role']
                    session['name'] = user['name']
                    if user['role'] == 'admin':
                        return redirect(url_for('admin.dashboard'))
                    elif user['role'] == 'faculty':
                        return redirect(url_for('faculty.dashboard'))
            
            flash('Invalid email, password, or role selection.', 'danger')
        except mysql.connector.Error as err:
            flash(f"Database error: {err}", 'danger')
        finally:
            cursor.close()
            db.close()
            
    return render_template('login.html')