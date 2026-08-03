"""
utils/gpa_calculator.py
Single source of truth for grading policy and CGPA calculations.
"""

GRADE_POINTS = {
    'A+': 4.00, 'A': 3.75, 'A-': 3.50,
    'B+': 3.25, 'B': 3.00, 'B-': 2.75,
    'C+': 2.50, 'C': 2.25, 'D': 2.00, 'F': 0.00
}

def marks_to_grade(marks) -> str:
    if marks is None:
        return 'F'
    try:
        marks = float(marks)
    except (ValueError, TypeError):
        return 'F'

    if marks > 100 or marks < 0:
        return 'F'

    if marks >= 80:    return 'A+'
    elif marks >= 75:  return 'A'
    elif marks >= 70:  return 'A-'
    elif marks >= 65:  return 'B+'
    elif marks >= 60:  return 'B'
    elif marks >= 55:  return 'B-'
    elif marks >= 50:  return 'C+'
    elif marks >= 45:  return 'C'
    elif marks >= 40:  return 'D'
    else:              return 'F'

def determine_completion(grade: str, exam_attendance: str) -> tuple[bool, bool]:
    if exam_attendance == 'absent' or grade == 'F':
        return False, True
    return True, False

def get_grade_point(grade: str) -> float:
    if not grade:
        return 0.00
    return GRADE_POINTS.get(str(grade).strip().upper(), 0.00)

def calculate_cgpa(completed_courses: list) -> tuple[float, float]:
    if not completed_courses:
        return 0.00, 0.00

    total_quality_points = 0.00
    total_attempted_credits = 0.00
    total_earned_credits = 0.00

    for course in completed_courses:
        grade_str = course.get('grade')
        try:
            credits = float(course.get('credits', 0))
        except (ValueError, TypeError):
            credits = 0.00

        if credits <= 0 or not grade_str:
            continue

        clean_grade = str(grade_str).strip().upper()
        if clean_grade in GRADE_POINTS:
            point = GRADE_POINTS[clean_grade]
            total_quality_points += point * credits
            total_attempted_credits += credits

            if clean_grade != 'F':
                total_earned_credits += credits

    if total_attempted_credits == 0:
        return 0.00, 0.00

    return round(total_quality_points / total_attempted_credits, 2), total_earned_credits