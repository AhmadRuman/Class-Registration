import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from class_registration import User, load_registrar
from class_registration.cli import main

# Keep password hashing cheap so the suite runs fast.
User.hash_iterations = 1_000


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmpdir.name, "test.db")

    def tearDown(self):
        self.tmpdir.cleanup()

    def run_cli(self, *argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(stdin)):
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["--db", self.db, *argv])
        return code, out.getvalue(), err.getvalue()

    def ok(self, *argv, stdin=""):
        code, out, err = self.run_cli(*argv, stdin=stdin)
        self.assertEqual(code, 0, err)
        return out

    def test_full_registration_flow(self):
        self.ok("init", "--max-credits", "10")
        self.ok(
            "course",
            "add",
            "CS101",
            "Intro",
            "--credits",
            "4",
            "--capacity",
            "1",
            "--meets",
            "Mon 09:00-10:30",
        )
        self.ok("instructor", "add", "E1", "jdoe", "Jane", "Doe", stdin="teach\n")
        self.ok("instructor", "assign", "E1", "CS101")
        self.ok("student", "add", "S1", "alice", "Alice", "Smith", stdin="pw1\n")
        self.ok("student", "add", "S2", "bob", "Bob", "Lee", stdin="pw2\n")

        self.assertIn("Enrolled S1", self.ok("register", "S1", "CS101"))
        self.assertIn("#1 on the waitlist", self.ok("register", "S2", "CS101"))
        out = self.ok("drop", "S1", "CS101")
        self.assertIn("Enrolled S2 from the waitlist", out)

        registrar = load_registrar(self.db)
        self.assertEqual(registrar.max_credits, 10)
        course = registrar.courses["CS101"]
        self.assertEqual([s.student_id for s in course.students], ["S2"])
        self.assertEqual(course.instructor.get_full_name(), "Jane Doe")
        self.assertTrue(registrar.students["S1"].check_password("pw1"))
        self.assertTrue(registrar.instructors["E1"].check_password("teach"))

    def test_course_add_with_prereqs_and_meetings(self):
        self.ok(
            "course",
            "add",
            "CS201",
            "Algorithms",
            "--prereq",
            "CS101",
            "--prereq",
            "MATH101",
            "--meets",
            "Mon 09:00-10:00",
            "--meets",
            "Wed 09:00-10:00",
        )
        out = self.ok("course", "show", "CS201")
        self.assertIn("Prerequisites: CS101, MATH101", out)
        self.assertIn("Meets:         Mon 09:00-10:00, Wed 09:00-10:00", out)

    def test_rule_violation_reports_error_and_saves_nothing(self):
        self.ok("course", "add", "CS201", "Algorithms", "--prereq", "CS101")
        self.ok("student", "add", "S1", "alice", "Alice", "Smith", stdin="pw\n")
        code, out, err = self.run_cli("register", "S1", "CS201")
        self.assertEqual(code, 1)
        self.assertIn("missing prerequisites", err)
        self.assertEqual(load_registrar(self.db).courses["CS201"].students, [])

        self.ok("student", "complete", "S1", "CS101")
        self.assertIn("Enrolled S1 in CS201", self.ok("register", "S1", "CS201"))

    def test_unknown_ids_are_errors(self):
        for argv in (
            ("course", "show", "NOPE"),
            ("student", "show", "S404"),
            ("instructor", "assign", "E404", "CS101"),
        ):
            code, _, err = self.run_cli(*argv)
            self.assertEqual(code, 1)
            self.assertIn("error:", err)

    def test_duplicate_ids_rejected(self):
        self.ok("student", "add", "S1", "alice", "Alice", "Smith", stdin="pw\n")
        code, _, err = self.run_cli("student", "add", "S1", "eve", "Eve", "X", stdin="pw\n")
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        self.ok("course", "add", "CS101", "Intro")
        code, _, _ = self.run_cli("course", "add", "CS101", "Again")
        self.assertEqual(code, 1)

    def test_empty_password_rejected(self):
        code, _, err = self.run_cli("student", "add", "S1", "alice", "Alice", "Smith", stdin="\n")
        self.assertEqual(code, 1)
        self.assertIn("Password must not be empty", err)

    def test_bad_meeting_time_rejected(self):
        code, _, err = self.run_cli("course", "add", "X", "Bad", "--meets", "Monday 9-10")
        self.assertEqual(code, 1)
        self.assertIn("invalid meeting time", err)

    def test_read_only_command_does_not_create_database(self):
        self.assertIn("No courses yet", self.ok("course", "list"))
        self.assertFalse(os.path.exists(self.db))

    def test_student_show_lists_schedule_and_waitlist(self):
        self.ok("course", "add", "A", "Alpha", "--capacity", "1")
        self.ok("course", "add", "B", "Beta", "--meets", "Tue 10:00-11:00")
        for sid in ("S1", "S2"):
            self.ok("student", "add", sid, sid.lower(), "First", sid, stdin="pw\n")
        self.ok("register", "S1", "A")
        self.ok("register", "S2", "A")
        self.ok("register", "S2", "B")
        out = self.ok("student", "show", "S2")
        self.assertIn("Credits:   3/18", out)
        self.assertIn("B  Beta (Tue 10:00-11:00)", out)
        self.assertIn("A  position 1", out)

    def test_course_list(self):
        self.ok("course", "add", "CS101", "Intro", "--capacity", "30")
        out = self.ok("course", "list")
        self.assertIn("CS101", out)
        self.assertIn("0/30", out)


if __name__ == "__main__":
    unittest.main()
