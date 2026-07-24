def marks_to_grade(marks):
    if marks >= 90:  return 'A+'
    elif marks >= 85: return 'A'
    elif marks >= 80: return 'A-'
    elif marks >= 75: return 'B+'
    elif marks >= 70: return 'B'
    elif marks >= 65: return 'B-'
    elif marks >= 60: return 'C+'
    elif marks >= 55: return 'C'
    elif marks >= 50: return 'D'
    else:             return 'F'

def calculate_gpa(grades):
    # grades = [{'marks': 92, 'credit_hours': 3}, ...]
    if not grades:
        return 0.0
    total_points  = sum(g['marks'] * g['credit_hours'] for g in grades)
    total_credits = sum(g['credit_hours'] for g in grades)
    return round(total_points / total_credits / 25, 2) if total_credits else 0.0