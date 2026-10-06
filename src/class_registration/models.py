"""Users, courses and meeting times."""

import hashlib
import hmac
import secrets
from datetime import time

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class User:
    # PBKDF2 work factor for newly set passwords. Each user keeps the count
    # their hash was made with, so raising this never invalidates old hashes.
    hash_iterations = 200_000

    def __init__(self, username, password, first_name, last_name):
        """Pass password=None to create a user whose hash is restored later."""
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self._salt = None
        self._password_hash = None
        self._iterations = None
        if password is not None:
            self.set_password(password)

    def _hash_password(self, password):
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), self._salt, self._iterations)

    def set_password(self, password):
        self._salt = secrets.token_bytes(16)
        self._iterations = self.hash_iterations
        self._password_hash = self._hash_password(password)

    def check_password(self, password):
        if self._password_hash is None:
            return False
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

    @classmethod
    def parse(cls, text):
        """Build a MeetingTime from text like 'Mon 09:00-10:30'."""
        try:
            day, hours = text.split()
            start, end = hours.split("-")
            return cls(day, time.fromisoformat(start), time.fromisoformat(end))
        except ValueError as e:
            raise ValueError(
                f"invalid meeting time {text!r} (expected e.g. 'Mon 09:00-10:30'): {e}"
            ) from None

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


class Admin(User):
    """Registrar staff: can manage courses, people and registrations."""

    def __init__(self, username, password, first_name, last_name, admin_id):
        super().__init__(username, password, first_name, last_name)
        self.admin_id = admin_id
