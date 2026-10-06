import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import time

from class_registration import (
    ENROLLED,
    Instructor,
    MeetingTime,
    Registrar,
    Student,
    User,
)
from class_registration.storage import load_registrar, save_registrar

# Keep password hashing cheap so the suite runs fast.
User.hash_iterations = 1_000


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "registrar.db")

        self.registrar = Registrar(max_credits=12)
        self.instructor = Instructor("jdoe", "teach", "Jane", "Doe", "E1")
        self.cs101 = self.registrar.create_course(
            "CS101",
            "Intro",
            credits=4,
            capacity=2,
            meeting_times=[
                MeetingTime("Mon", time(9), time(10, 30)),
                MeetingTime("Wed", time(9), time(10, 30)),
            ],
        )
        self.cs201 = self.registrar.create_course(
            "CS201", "Algorithms", prerequisites=["CS101", "MATH101"]
        )
        self.registrar.assign_instructor(self.cs101, self.instructor)
        self.registrar.assign_instructor(self.cs201, self.instructor)

        self.students = [
            Student(f"user{n}", f"pw{n}", "First", f"Last{n}", f"S{n}") for n in range(1, 5)
        ]
        for s in self.students:
            self.registrar.register_student(s, self.cs101)
        self.students[0].complete_course("CS101")
        self.students[0].complete_course("MATH101")
        self.registrar.add_instructor(Instructor("idle", "pw", "No", "Courses", "E2"))
        self.registrar.add_student(Student("new", "pw", "Not", "Registered", "S9"))

    def tearDown(self):
        self.tmpdir.cleanup()

    def round_trip(self):
        save_registrar(self.registrar, self.path)
        return load_registrar(self.path)

    def test_round_trip_preserves_courses_and_rosters(self):
        loaded = self.round_trip()
        self.assertEqual(loaded.max_credits, 12)
        for code in ("CS101", "CS201"):
            self.assertEqual(
                loaded.pull_course_registration_info(loaded.courses[code]),
                self.registrar.pull_course_registration_info(self.registrar.courses[code]),
            )
        cs101 = loaded.courses["CS101"]
        self.assertEqual(repr(cs101.meeting_times), "[Mon 09:00-10:30, Wed 09:00-10:30]")
        self.assertEqual(loaded.courses["CS201"].prerequisites, {"CS101", "MATH101"})
        self.assertEqual(loaded.students["S1"].completed_courses, {"CS101", "MATH101"})

    def test_round_trip_keeps_people_without_courses(self):
        loaded = self.round_trip()
        self.assertIn("S9", loaded.students)
        self.assertIn("E2", loaded.instructors)

    def test_loaded_objects_are_shared_not_copied(self):
        loaded = self.round_trip()
        self.assertIs(loaded.courses["CS101"].instructor, loaded.courses["CS201"].instructor)
        self.assertIs(loaded.courses["CS101"].students[0], loaded.students["S1"])

    def test_passwords_survive_round_trip(self):
        loaded = self.round_trip()
        self.assertTrue(loaded.students["S2"].check_password("pw2"))
        self.assertFalse(loaded.students["S2"].check_password("pw1"))
        self.assertTrue(loaded.instructors["E1"].check_password("teach"))

    def test_plain_passwords_not_in_file(self):
        save_registrar(self.registrar, self.path)
        with open(self.path, "rb") as f:
            self.assertNotIn(b"teach", f.read())

    def test_loaded_registrar_keeps_working(self):
        loaded = self.round_trip()
        s1, s3 = loaded.students["S1"], loaded.students["S3"]
        promoted = loaded.drop_student(s1, loaded.courses["CS101"])
        self.assertIs(promoted, s3)
        self.assertEqual(loaded.register_student(s1, loaded.courses["CS201"]), ENROLLED)

    def test_saving_twice_replaces_contents(self):
        save_registrar(self.registrar, self.path)
        self.registrar.drop_student(self.students[0], self.cs101)
        loaded = self.round_trip()
        self.assertEqual([s.student_id for s in loaded.courses["CS101"].students], ["S2", "S3"])

    def test_failed_save_keeps_previous_contents(self):
        save_registrar(self.registrar, self.path)
        # A roster entry for a student the registrar doesn't know breaks a foreign key.
        self.cs101.students.append(Student("ghost", "pw", "G", "H", "S404"))
        with self.assertRaises(sqlite3.IntegrityError):
            save_registrar(self.registrar, self.path)
        loaded = load_registrar(self.path)
        self.assertEqual([s.student_id for s in loaded.courses["CS101"].students], ["S1", "S2"])

    def test_missing_file_loads_empty_registrar(self):
        loaded = load_registrar(os.path.join(self.tmpdir.name, "new.db"))
        self.assertEqual(loaded.courses, {})
        self.assertEqual(loaded.max_credits, 18)

    def test_unknown_schema_version_rejected(self):
        # closing() matters: sqlite3's own context manager only commits, and
        # Windows can't delete the temp file while a connection is open.
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("PRAGMA user_version = 99")
        with self.assertRaisesRegex(ValueError, "schema version 99"):
            load_registrar(self.path)


if __name__ == "__main__":
    unittest.main()
