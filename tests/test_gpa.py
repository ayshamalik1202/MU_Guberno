import unittest
from gpa_calculator import get_grade_point, calculate_cgpa

class TestGPACalculator(unittest.TestCase):

    def test_get_grade_point_valid(self):
        """Test valid grade point mappings."""
        self.assertEqual(get_grade_point('A+'), 4.00)
        self.assertEqual(get_grade_point('A'), 3.75)
        self.assertEqual(get_grade_point('B+'), 3.25)
        self.assertEqual(get_grade_point('F'), 0.00)

    def test_get_grade_point_case_insensitive_and_whitespace(self):
        """Test grade lookup with lowercase letters and padding."""
        self.assertEqual(get_grade_point('a+'), 4.00)
        self.assertEqual(get_grade_point(' b '), 3.00)

    def test_get_grade_point_invalid(self):
        """Test invalid grade entries return 0.0."""
        self.assertEqual(get_grade_point('INVALID'), 0.00)
        self.assertEqual(get_grade_point(''), 0.00)
        self.assertEqual(get_grade_point(None), 0.00)

    def test_calculate_cgpa_standard_case(self):
        """Test CGPA calculation with a typical mix of courses."""
        courses = [
            {'grade': 'A+', 'credits': 3.0}, # 4.00 * 3 = 12.00
            {'grade': 'A',  'credits': 3.0}, # 3.75 * 3 = 11.25
            {'grade': 'B+', 'credits': 1.5}  # 3.25 * 1.5 = 4.875
        ]
        # Total Points: 28.125, Total Credits: 7.5 -> CGPA: 3.75
        cgpa, credits = calculate_cgpa(courses)
        self.assertEqual(cgpa, 3.75)
        self.assertEqual(credits, 7.5)

    def test_calculate_cgpa_with_failures(self):
        """Test that failed courses ('F') do not add to earned completed credits."""
        courses = [
            {'grade': 'A+', 'credits': 3.0}, # Earned
            {'grade': 'F',  'credits': 3.0}  # Failed - should be ignored in completed credits
        ]
        cgpa, credits = calculate_cgpa(courses)
        self.assertEqual(cgpa, 4.00)
        self.assertEqual(credits, 3.0)

    def test_calculate_cgpa_empty_or_malformed(self):
        """Test empty input and unexpected data types."""
        self.assertEqual(calculate_cgpa([]), (0.00, 0.00))
        
        malformed_courses = [
            {'grade': 'A', 'credits': 'invalid_number'},
            {'grade': None, 'credits': 3.0}
        ]
        self.assertEqual(calculate_cgpa(malformed_courses), (0.00, 0.00))

if __name__ == '__main__':
    unittest.main()