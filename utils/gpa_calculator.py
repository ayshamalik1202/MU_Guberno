"""
utils/gpa_calculator.py
Grade computation (marks -> letter grade), CGPA calculation, and
pass/fail -> completion status logic used by the admin approval pipeline.
"""

GRADE_POINTS = {
    'A+': 4.00,
    'A':  3.75,
    'A-': 3.50,
    'B+': 3.25,
    'B':  3.00,
    'B-': 2.75,
    'C+': 2.50,
    'C':  2.25,
    'D':  2.00,
    'F':  0.00
}


def marks_to_grade(marks) -> str:
    """
    Converts raw marks (0-100) into the official letter grade.
    This is the single source of truth for grading policy — faculty submit
    marks, and this function is what the admin-approval step calls to turn
    those marks into the letter grade that gets stored and published.
    """
    if marks is None:
        return 'F'
    try:
        marks = float(marks)
    except (ValueError, TypeError):
        return 'F'

    if marks >= 90: return 'A+'
    elif marks >= 85: return 'A'
    elif marks >= 80: return 'A-'
    elif marks >= 75: return 'B+'
    elif marks >= 70: return 'B'
    elif marks >= 65: return 'B-'
    elif marks >= 60: return 'C+'
    elif marks >= 55: return 'C'
    elif marks >= 50: return 'D'
    else:              return 'F'


def determine_completion(grade: str, exam_attendance: str) -> tuple[bool, bool]:
    """
    Given a computed letter grade and exam attendance, decides whether the
    credit counts as completed and whether the course needs a supplementary
    retake.

    Returns:
        tuple: (credit_completed: bool, is_supplementary: bool)
    """
    if exam_attendance == 'absent' or grade == 'F':
        return False, True
    return True, False


def get_grade_point(grade: str) -> float:
    """Returns the numeric quality point for a given letter grade."""
    if not grade:
        return 0.00
    return GRADE_POINTS.get(grade.strip().upper(), 0.00)


def calculate_cgpa(completed_courses: list) -> tuple[float, float]:
    """
    Calculates the CGPA and total earned credits from a list of course records.

    Expected item structure in list:
        {'grade': 'A', 'credits': 3.0} or {'grade': 'B+', 'credits': 1.5}

    Returns:
        tuple: (cgpa: float, total_credits_earned: float)
    """
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

            if clean_grade != 'F' and point > 0:
                total_earned_credits += credits

    if total_attempted_credits == 0:
        return 0.00, 0.00

    cgpa = round(total_quality_points / total_attempted_credits, 2)

    return cgpa, total_earned_credits