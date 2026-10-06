import unittest

from class_registration import (
    Instructor,
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
