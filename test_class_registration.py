import unittest
from datetime import time

from class_registration import (
    ENROLLED,
    WAITLISTED,
    Instructor,
    MeetingTime,
    RegistrationError,
    Registrar,
    Student,
)


class RegistrarTests(unittest.TestCase):
    def setUp(self):
        self.registrar = Registrar()
        self.cs101 = self.registrar.create_course("CS101", "Intro to Programming")
        self.instructor = Instructor("jdoe", "secret", "Jane", "Doe", "E1")
        self.alice = Student("alice", "pw1", "Alice", "Smith", "S1")
        self.bob = Student("bob", "pw2", "Bob", "Lee", "S2")

    def test_register_student_with_instructor(self):
        self.registrar.assign_instructor(self.cs101, self.instructor)
        self.registrar.register_student(self.alice, self.cs101)
        info = self.registrar.pull_course_registration_info(self.cs101)
        self.assertEqual(info["Instructor"], "Jane Doe")
        self.assertEqual(info["Registered Students"], ["S1"])

    def test_register_student_before_instructor_assigned(self):
        self.registrar.register_student(self.alice, self.cs101)
        info = self.registrar.pull_course_registration_info(self.cs101)
        self.assertIsNone(info["Instructor"])
        self.assertEqual(info["Registered Students"], ["S1"])

    def test_instructor_teaching_two_courses_keeps_rosters_separate(self):
        cs102 = self.registrar.create_course("CS102", "Data Structures")
        self.registrar.assign_instructor(self.cs101, self.instructor)
        self.registrar.assign_instructor(cs102, self.instructor)
        self.registrar.register_student(self.alice, self.cs101)
        self.registrar.register_student(self.bob, cs102)
        self.assertEqual(
            self.registrar.pull_course_registration_info(self.cs101)["Registered Students"],
            ["S1"],
        )
        self.assertEqual(
            self.registrar.pull_course_registration_info(cs102)["Registered Students"],
            ["S2"],
        )

    def test_duplicate_course_code_rejected(self):
        with self.assertRaises(RegistrationError):
            self.registrar.create_course("CS101", "Duplicate")

    def test_duplicate_registration_rejected(self):
        self.registrar.register_student(self.alice, self.cs101)
        with self.assertRaises(RegistrationError):
            self.registrar.register_student(self.alice, self.cs101)

    def test_conflicting_student_id_rejected(self):
        self.registrar.register_student(self.alice, self.cs101)
        impostor = Student("eve", "pw", "Eve", "X", "S1")
        with self.assertRaises(RegistrationError):
            self.registrar.register_student(impostor, self.cs101)

    def test_conflicting_employee_id_rejected(self):
        self.registrar.assign_instructor(self.cs101, self.instructor)
        other = Instructor("other", "pw", "Other", "Person", "E1")
        with self.assertRaises(RegistrationError):
            self.registrar.assign_instructor(self.cs101, other)

    def test_unknown_course_rejected(self):
        other_registrar = Registrar()
        foreign = other_registrar.create_course("CS999", "Elsewhere")
        with self.assertRaises(RegistrationError):
            self.registrar.register_student(self.alice, foreign)
        self.assertIsNone(self.registrar.pull_course_registration_info(foreign))


def make_student(n):
    return Student(f"user{n}", "pw", "First", f"Last{n}", f"S{n}")


class CapacityAndWaitlistTests(unittest.TestCase):
    def setUp(self):
        self.registrar = Registrar()
        self.course = self.registrar.create_course("CS101", "Intro", capacity=2)
        self.s1, self.s2, self.s3, self.s4 = (make_student(n) for n in range(1, 5))

    def test_full_course_waitlists_students(self):
        self.assertEqual(self.registrar.register_student(self.s1, self.course), ENROLLED)
        self.assertEqual(self.registrar.register_student(self.s2, self.course), ENROLLED)
        self.assertEqual(self.registrar.register_student(self.s3, self.course), WAITLISTED)
        info = self.registrar.pull_course_registration_info(self.course)
        self.assertEqual(info["Registered Students"], ["S1", "S2"])
        self.assertEqual(info["Waitlist"], ["S3"])

    def test_drop_promotes_first_waitlisted_student(self):
        for s in (self.s1, self.s2, self.s3, self.s4):
            self.registrar.register_student(s, self.course)
        promoted = self.registrar.drop_student(self.s1, self.course)
        self.assertIs(promoted, self.s3)
        self.assertEqual(self.course.students, [self.s2, self.s3])
        self.assertEqual(self.course.waitlist, [self.s4])

    def test_drop_from_waitlist_does_not_promote(self):
        for s in (self.s1, self.s2, self.s3):
            self.registrar.register_student(s, self.course)
        self.assertIsNone(self.registrar.drop_student(self.s3, self.course))
        self.assertEqual(self.course.waitlist, [])
        self.assertEqual(self.course.students, [self.s1, self.s2])

    def test_promotion_skips_student_who_became_ineligible(self):
        clash = self.registrar.create_course(
            "CS200", "Clash", meeting_times=[MeetingTime("Mon", time(9), time(10))]
        )
        self.course.meeting_times = [MeetingTime("Mon", time(9, 30), time(11))]
        for s in (self.s1, self.s2, self.s3, self.s4):
            self.registrar.register_student(s, self.course)
        # s3 enrolls in a clashing course while waiting
        self.registrar.register_student(self.s3, clash)
        promoted = self.registrar.drop_student(self.s1, self.course)
        self.assertIs(promoted, self.s4)
        self.assertEqual(self.course.waitlist, [self.s3])

    def test_already_waitlisted_rejected(self):
        for s in (self.s1, self.s2, self.s3):
            self.registrar.register_student(s, self.course)
        with self.assertRaises(RegistrationError):
            self.registrar.register_student(self.s3, self.course)

    def test_drop_unregistered_student_rejected(self):
        with self.assertRaises(RegistrationError):
            self.registrar.drop_student(self.s1, self.course)

    def test_invalid_capacity_rejected(self):
        with self.assertRaises(ValueError):
            self.registrar.create_course("CS102", "Bad", capacity=0)


class PrerequisiteTests(unittest.TestCase):
    def setUp(self):
        self.registrar = Registrar()
        self.cs201 = self.registrar.create_course(
            "CS201", "Algorithms", prerequisites=["CS101", "MATH101"]
        )
        self.student = make_student(1)

    def test_missing_prerequisites_rejected(self):
        self.student.complete_course("CS101")
        with self.assertRaisesRegex(RegistrationError, "MATH101"):
            self.registrar.register_student(self.student, self.cs201)
        self.assertNotIn("S1", self.registrar.students)

    def test_completed_prerequisites_allowed(self):
        self.student.complete_course("CS101")
        self.student.complete_course("MATH101")
        self.assertEqual(self.registrar.register_student(self.student, self.cs201), ENROLLED)

    def test_course_cannot_require_itself(self):
        with self.assertRaises(ValueError):
            self.registrar.create_course("CS300", "Loop", prerequisites=["CS300"])


class CreditLimitTests(unittest.TestCase):
    def test_credit_limit_enforced(self):
        registrar = Registrar(max_credits=7)
        a = registrar.create_course("A", "A", credits=4)
        b = registrar.create_course("B", "B", credits=3)
        c = registrar.create_course("C", "C", credits=1)
        student = make_student(1)
        registrar.register_student(student, a)
        registrar.register_student(student, b)
        self.assertEqual(registrar.get_student_credits(student), 7)
        with self.assertRaisesRegex(RegistrationError, "credit limit"):
            registrar.register_student(student, c)

    def test_dropping_frees_credits(self):
        registrar = Registrar(max_credits=4)
        a = registrar.create_course("A", "A", credits=4)
        b = registrar.create_course("B", "B", credits=4)
        student = make_student(1)
        registrar.register_student(student, a)
        registrar.drop_student(student, a)
        self.assertEqual(registrar.register_student(student, b), ENROLLED)


class ScheduleConflictTests(unittest.TestCase):
    def setUp(self):
        self.registrar = Registrar()
        self.morning = self.registrar.create_course(
            "A", "Morning", meeting_times=[MeetingTime("Mon", time(9), time(10, 30))]
        )
        self.student = make_student(1)
        self.registrar.register_student(self.student, self.morning)

    def test_overlapping_course_rejected(self):
        overlap = self.registrar.create_course(
            "B", "Overlap", meeting_times=[MeetingTime("Mon", time(10), time(11))]
        )
        with self.assertRaisesRegex(RegistrationError, "conflicts with A"):
            self.registrar.register_student(self.student, overlap)

    def test_back_to_back_and_other_day_allowed(self):
        back_to_back = self.registrar.create_course(
            "B", "Next", meeting_times=[MeetingTime("Mon", time(10, 30), time(12))]
        )
        other_day = self.registrar.create_course(
            "C", "Tuesday", meeting_times=[MeetingTime("Tue", time(9), time(10, 30))]
        )
        self.assertEqual(self.registrar.register_student(self.student, back_to_back), ENROLLED)
        self.assertEqual(self.registrar.register_student(self.student, other_day), ENROLLED)

    def test_invalid_meeting_time_rejected(self):
        with self.assertRaises(ValueError):
            MeetingTime("Mon", time(11), time(10))
        with self.assertRaises(ValueError):
            MeetingTime("Monday", time(9), time(10))


class PasswordTests(unittest.TestCase):
    def test_password_is_hashed_not_stored(self):
        student = Student("alice", "pw1", "Alice", "Smith", "S1")
        self.assertFalse(hasattr(student, "password"))
        self.assertTrue(student.check_password("pw1"))
        self.assertFalse(student.check_password("wrong"))

    def test_same_password_gets_different_hashes(self):
        a = Student("a", "same", "A", "A", "S1")
        b = Student("b", "same", "B", "B", "S2")
        self.assertNotEqual(a._password_hash, b._password_hash)


if __name__ == "__main__":
    unittest.main()
