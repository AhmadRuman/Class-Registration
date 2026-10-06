import hashlib
import hmac
import secrets


class RegistrationError(Exception):
    """Raised when a registrar operation is not allowed."""


class User:
    _HASH_ITERATIONS = 200_000

    def __init__(self, username, password, first_name, last_name):
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self._salt = secrets.token_bytes(16)
        self._password_hash = self._hash_password(password)

    def _hash_password(self, password):
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), self._salt, self._HASH_ITERATIONS
        )

    def check_password(self, password):
        return hmac.compare_digest(self._password_hash, self._hash_password(password))

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"


class Course:
    def __init__(self, course_code, course_name):
        self.course_code = course_code
        self.course_name = course_name
        self.instructor = None
        self.students = []


class Instructor(User):
    def __init__(self, username, password, first_name, last_name, employee_id):
        super().__init__(username, password, first_name, last_name)
        self.employee_id = employee_id


class Student(User):
    def __init__(self, username, password, first_name, last_name, student_id):
        super().__init__(username, password, first_name, last_name)
        self.student_id = student_id


class Registrar:
    def __init__(self):
        self.courses = {}
        self.instructors = {}
        self.students = {}

    def create_course(self, course_code, course_name):
        if course_code in self.courses:
            raise RegistrationError(f"Course {course_code} already exists")
        course = Course(course_code, course_name)
        self.courses[course_code] = course
        return course

    def _check_course(self, course):
        if self.courses.get(course.course_code) is not course:
            raise RegistrationError(
                f"Course {course.course_code} is not managed by this registrar"
            )

    def assign_instructor(self, course, instructor):
        self._check_course(course)
        existing = self.instructors.setdefault(instructor.employee_id, instructor)
        if existing is not instructor:
            raise RegistrationError(
                f"Employee ID {instructor.employee_id} belongs to another instructor"
            )
        course.instructor = instructor

    def register_student(self, student, course):
        self._check_course(course)
        existing = self.students.setdefault(student.student_id, student)
        if existing is not student:
            raise RegistrationError(
                f"Student ID {student.student_id} belongs to another student"
            )
        if student in course.students:
            raise RegistrationError(
                f"Student {student.student_id} is already registered in {course.course_code}"
            )
        course.students.append(student)

    def pull_course_registration_info(self, course):
        if self.courses.get(course.course_code) is not course:
            return None
        return {
            "Course Code": course.course_code,
            "Course Name": course.course_name,
            "Instructor": course.instructor.get_full_name() if course.instructor else None,
            "Registered Students": [student.student_id for student in course.students],
        }
