import os
from flask import Flask, redirect, url_for, session
from database import init_db

# Import your route blueprints
from routes.auth import auth_bp
from routes.student import student_bp
from routes.faculty import faculty_bp
from routes.admin import admin_bp

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'a_highly_secure_dev_key_12345')

# Initialize database connections (assuming your database.py handles this setup)
init_db(app)

# Register Blueprints with appropriate URL prefixes
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(student_bp, url_prefix='/student')
app.register_blueprint(faculty_bp, url_prefix='/faculty')
app.register_blueprint(admin_bp, url_prefix='/admin')

@app.route('/')
def home():
    # If a user is already logged in, send them to their respective dashboard
    if 'role' in session:
        if session['role'] == 'student':
            return redirect(url_for('student.dashboard'))
        elif session['role'] == 'faculty':
            return redirect(url_for('faculty.dashboard'))
        elif session['role'] == 'admin':
            return redirect(url_for('admin.dashboard'))
    
    # Otherwise, direct them to log in
    return redirect(url_for('auth.login'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)