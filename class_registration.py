import hashlib
import hmac
import secrets
from datetime import time

ENROLLED = "enrolled"
WAITLISTED = "waitlisted"

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


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


class MeetingTime:
    def __init__(self, day, start, end):
        if day not in DAYS:
            raise ValueError(f"day must be one of {DAYS}, got {day!r}")
        if not (isinstance(start, time) and isinstance(end, time)):
            raise TypeError("start and end must be datetime.time objects")
        if start >= end:
            raise ValueError("start must be before end")
        self.day = day
        self.start = start
        self.end = end

    def overlaps(self, other):
        return self.day == other.day and self.start < other.end and other.start < self.end

    def __repr__(self):
        return f"{self.day} {self.start:%H:%M}-{self.end:%H:%M}"


class Course:
    def __init__(
        self,
        course_code,
        course_name,
        credits=3,
        capacity=None,
        prerequisites=(),
        meeting_times=(),
    ):
        if credits <= 0:
            raise ValueError("credits must be positive")
        if capacity is not None and capacity <= 0:
            raise ValueError("capacity must be positive or None for unlimited")
        if course_code in prerequisites:
            raise ValueError("a course cannot be its own prerequisite")
        self.course_code = course_code
        self.course_name = course_name
        self.credits = credits
        self.capacity = capacity
        self.prerequisites = set(prerequisites)
        self.meeting_times = list(meeting_times)
        self.instructor = None
        self.students = []
        self.waitlist = []

    def is_full(self):
        return self.capacity is not None and len(self.students) >= self.capacity

    def conflicts_with(self, other):
        return any(a.overlaps(b) for a in self.meeting_times for b in other.meeting_times)


class Instructor(User):
    def __init__(self, username, password, first_name, last_name, employee_id):
        super().__init__(username, password, first_name, last_name)
        self.employee_id = employee_id


class Student(User):
    def __init__(self, username, password, first_name, last_name, student_id):
        super().__init__(username, password, first_name, last_name)
        self.student_id = student_id
        self.completed_courses = set()

    def complete_course(self, course_code):
        self.completed_courses.add(course_code)


class Registrar:
    def __init__(self, max_credits=18):
        self.max_credits = max_credits
        self.courses = {}
        self.instructors = {}
        self.students = {}

    def create_course(self, course_code, course_name, **options):
        if course_code in self.courses:
            raise RegistrationError(f"Course {course_code} already exists")
        course = Course(course_code, course_name, **options)
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

    def get_student_courses(self, student):
        return [c for c in self.courses.values() if student in c.students]

    def get_student_credits(self, student):
        return sum(c.credits for c in self.get_student_courses(student))

    def _check_eligibility(self, student, course):
        missing = course.prerequisites - student.completed_courses
        if missing:
            raise RegistrationError(
                f"Student {student.student_id} is missing prerequisites for "
                f"{course.course_code}: {', '.join(sorted(missing))}"
            )
        if self.get_student_credits(student) + course.credits > self.max_credits:
            raise RegistrationError(
                f"Registering for {course.course_code} would put student "
                f"{student.student_id} over the {self.max_credits}-credit limit"
            )
        for enrolled in self.get_student_courses(student):
            if course.conflicts_with(enrolled):
                raise RegistrationError(
                    f"{course.course_code} conflicts with {enrolled.course_code} "
                    f"in student {student.student_id}'s schedule"
                )

    def register_student(self, student, course):
        """Enroll the student, or waitlist them if the course is full.

        Returns ENROLLED or WAITLISTED.
        """
        self._check_course(course)
        existing = self.students.get(student.student_id)
        if existing is not None and existing is not student:
            raise RegistrationError(
                f"Student ID {student.student_id} belongs to another student"
            )
        if student in course.students:
            raise RegistrationError(
                f"Student {student.student_id} is already registered in {course.course_code}"
            )
        if student in course.waitlist:
            raise RegistrationError(
                f"Student {student.student_id} is already on the waitlist for {course.course_code}"
            )
        self._check_eligibility(student, course)
        self.students[student.student_id] = student
        if course.is_full():
            course.waitlist.append(student)
            return WAITLISTED
        course.students.append(student)
        return ENROLLED

    def drop_student(self, student, course):
        """Remove the student from the course or its waitlist.

        Dropping an enrolled student frees a seat, which goes to the first
        waitlisted student who is still eligible. Returns that student, or None.
        """
        self._check_course(course)
        if student in course.waitlist:
            course.waitlist.remove(student)
            return None
        if student not in course.students:
            raise RegistrationError(
                f"Student {student.student_id} is not registered in {course.course_code}"
            )
        course.students.remove(student)
        return self._fill_from_waitlist(course)

    def _fill_from_waitlist(self, course):
        for candidate in course.waitlist:
            try:
                self._check_eligibility(candidate, course)
            except RegistrationError:
                continue
            course.waitlist.remove(candidate)
            course.students.append(candidate)
            return candidate
        return None

    def pull_course_registration_info(self, course):
        if self.courses.get(course.course_code) is not course:
            return None
        return {
            "Course Code": course.course_code,
            "Course Name": course.course_name,
            "Credits": course.credits,
            "Capacity": course.capacity,
            "Instructor": course.instructor.get_full_name() if course.instructor else None,
            "Registered Students": [student.student_id for student in course.students],
            "Waitlist": [student.student_id for student in course.waitlist],
        }
