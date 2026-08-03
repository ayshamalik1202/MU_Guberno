CREATE DATABASE IF NOT EXISTS MU_Guberno;
USE MU_Guberno;

-- 1. Students Table
CREATE TABLE IF NOT EXISTS students (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    gpa DECIMAL(3,2) DEFAULT NULL,
    profile_locked BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Staff Table (Faculty and Admins)
CREATE TABLE IF NOT EXISTS staff (
    id INT AUTO_INCREMENT PRIMARY KEY,
    staff_id VARCHAR(50) UNIQUE,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    role ENUM('admin', 'faculty') NOT NULL,
    approval_status ENUM('pending', 'approved', 'rejected') DEFAULT 'approved',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Courses Table
CREATE TABLE IF NOT EXISTS courses (
    id INT AUTO_INCREMENT PRIMARY KEY,
    course_code VARCHAR(20) UNIQUE NOT NULL,
    course_name VARCHAR(100) NOT NULL
);
CREATE TABLE IF NOT EXISTS departments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    short_form VARCHAR(20) NOT NULL UNIQUE
);

-- 4. Semesters Table
CREATE TABLE IF NOT EXISTS semesters (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    is_current BOOLEAN DEFAULT FALSE,
    fee_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
    result_published BOOLEAN DEFAULT FALSE,
    result_publish_date DATETIME DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. Curriculum Table
CREATE TABLE IF NOT EXISTS curriculum (
    id INT AUTO_INCREMENT PRIMARY KEY,
    course_id INT NOT NULL,
    program VARCHAR(100) NOT NULL DEFAULT 'BSc in CSE',
    credits DECIMAL(3,1) NOT NULL,
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
);

-- 6. Course Offerings Table
CREATE TABLE IF NOT EXISTS course_offerings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    course_id INT NOT NULL,
    semester_id INT NOT NULL,
    faculty_id INT,
    class_time VARCHAR(100),
    room VARCHAR(50),
    submission_status ENUM(
        'draft', 
        'submitted_by_faculty', 
        'approved_by_admin', 
        'revision_requested', 
        'published'
    ) DEFAULT 'draft',
    submitted_at DATETIME DEFAULT NULL,
    approved_at DATETIME DEFAULT NULL,
    approved_by_admin_id INT DEFAULT NULL,
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE,
    FOREIGN KEY (semester_id) REFERENCES semesters(id) ON DELETE CASCADE,
    FOREIGN KEY (faculty_id) REFERENCES staff(id) ON DELETE SET NULL,
    FOREIGN KEY (approved_by_admin_id) REFERENCES staff(id) ON DELETE SET NULL
);

-- 7. Enrollments Table (Includes admin_remarks)
CREATE TABLE IF NOT EXISTS enrollments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    course_offering_id INT NOT NULL,
    continuous_marks DECIMAL(5,2) DEFAULT 0.00,
    final_exam_marks DECIMAL(5,2) DEFAULT 0.00,
    marks_obtained DECIMAL(5,2) DEFAULT 0.00,
    grade VARCHAR(5) DEFAULT NULL,
    grade_point DECIMAL(3,2) DEFAULT 0.00,
    exam_attendance ENUM('present', 'absent') DEFAULT 'present',
    submission_status ENUM(
        'not_submitted',
        'submitted_by_faculty',
        'approved_by_admin',
        'published'
    ) DEFAULT 'not_submitted',
    admin_remarks TEXT DEFAULT NULL,
    is_supplementary BOOLEAN DEFAULT FALSE,
    credit_completed BOOLEAN DEFAULT FALSE,
    is_locked BOOLEAN DEFAULT FALSE,
    submitted_by INT DEFAULT NULL,
    submitted_at DATETIME DEFAULT NULL,
    approved_by INT DEFAULT NULL,
    approved_at DATETIME DEFAULT NULL,
    UNIQUE KEY unique_enrollment (student_id, course_offering_id),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (course_offering_id) REFERENCES course_offerings(id) ON DELETE CASCADE,
    FOREIGN KEY (submitted_by) REFERENCES staff(id) ON DELETE SET NULL,
    FOREIGN KEY (approved_by) REFERENCES staff(id) ON DELETE SET NULL
);

-- 8. Service Requests Table
CREATE TABLE IF NOT EXISTS service_requests (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    service_type VARCHAR(100) NOT NULL,
    details TEXT,
    status ENUM('Pending', 'Approved', 'Rejected') DEFAULT 'Pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
);

-- 9. Payments Table
CREATE TABLE IF NOT EXISTS payments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    semester_id INT NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    method ENUM('mobile_banking', 'online_banking') NOT NULL,
    account_reference VARCHAR(100) NOT NULL,
    status ENUM('pending', 'verified', 'rejected') DEFAULT 'pending',
    receipt_no VARCHAR(50) DEFAULT NULL,
    verified_by INT DEFAULT NULL,
    verified_at DATETIME DEFAULT NULL,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (semester_id) REFERENCES semesters(id) ON DELETE CASCADE,
    FOREIGN KEY (verified_by) REFERENCES staff(id) ON DELETE SET NULL
);

-- 10. Complaints Table
CREATE TABLE IF NOT EXISTS complaints (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    category ENUM('result', 'payment', 'access', 'other') NOT NULL,
    subject VARCHAR(150) NOT NULL,
    message TEXT NOT NULL,
    status ENUM('pending', 'resolved') DEFAULT 'pending',
    admin_response TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME DEFAULT NULL,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
);

-- 11. Result Complaints Table (For direct grade reviews by faculty)
CREATE TABLE IF NOT EXISTS result_complaints (
    id INT AUTO_INCREMENT PRIMARY KEY,
    enrollment_id INT NOT NULL,
    reason TEXT NOT NULL,
    status ENUM('pending', 'sent_to_faculty', 'resolved') DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (enrollment_id) REFERENCES enrollments(id) ON DELETE CASCADE
);

-- 12. Grade Audit Logs
CREATE TABLE IF NOT EXISTS grade_audit_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    enrollment_id INT NOT NULL,
    admin_id INT NOT NULL,
    old_continuous DECIMAL(5,2),
    new_continuous DECIMAL(5,2),
    old_final DECIMAL(5,2),
    new_final DECIMAL(5,2),
    reason TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (enrollment_id) REFERENCES enrollments(id) ON DELETE CASCADE,
    FOREIGN KEY (admin_id) REFERENCES staff(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS class_times (
    id INT AUTO_INCREMENT PRIMARY KEY,
    day_of_week ENUM('Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday') NOT NULL,
    time_slot VARCHAR(30) NOT NULL,
    UNIQUE KEY unique_day_slot (day_of_week, time_slot)
);

CREATE TABLE IF NOT EXISTS rooms (
    id INT AUTO_INCREMENT PRIMARY KEY,
    room_name VARCHAR(20) NOT NULL UNIQUE
);
UPDATE staff SET approval_status = 'approved' WHERE approval_status IS NULL OR approval_status = 'pending';