"""Registration rules: enrollment, waitlists, prerequisites, credits, conflicts."""

from .exceptions import RegistrationError
from .models import Course

ENROLLED = "enrolled"
WAITLISTED = "waitlisted"


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
            raise RegistrationError(f"Course {course.course_code} is not managed by this registrar")

    def _check_new_student(self, student):
        existing = self.students.get(student.student_id)
        if existing is not None and existing is not student:
            raise RegistrationError(f"Student ID {student.student_id} belongs to another student")

    def add_student(self, student):
        self._check_new_student(student)
        self.students[student.student_id] = student

    def add_instructor(self, instructor):
        existing = self.instructors.setdefault(instructor.employee_id, instructor)
        if existing is not instructor:
            raise RegistrationError(
                f"Employee ID {instructor.employee_id} belongs to another instructor"
            )

    def assign_instructor(self, course, instructor):
        self._check_course(course)
        self.add_instructor(instructor)
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
        self._check_new_student(student)
        if student in course.students:
            raise RegistrationError(
                f"Student {student.student_id} is already registered in {course.course_code}"
            )
        if student in course.waitlist:
            raise RegistrationError(
                f"Student {student.student_id} is already on the waitlist for {course.course_code}"
            )
        self._check_eligibility(student, course)
        self.add_student(student)
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
