import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from class_registration import User, load_registrar
from class_registration.cli import main

# Keep password hashing cheap so the suite runs fast.
User.hash_iterations = 1_000


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmpdir.name, "test.db")
        session_file = os.path.join(self.tmpdir.name, "session.json")
        env = mock.patch.dict(os.environ, {"CLASS_REG_SESSION_FILE": session_file})
        env.start()
        self.addCleanup(env.stop)

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

    def fails(self, *argv, stdin="", message=""):
        code, _, err = self.run_cli(*argv, stdin=stdin)
        self.assertEqual(code, 1)
        self.assertIn(message, err)
        return err

    def login(self, username, password="pw"):
        return self.ok("login", username, stdin=f"{password}\n")

    def setup_school(self):
        """Admin, instructor E1 teaching CS101, students S1 and S2; logged in as admin."""
        self.ok("admin", "add", "A1", "root", "Ada", "Admin", stdin="pw\n")
        self.login("root")
        self.ok("course", "add", "CS101", "Intro", "--capacity", "1", "--meets", "Mon 09:00-10:30")
        self.ok("course", "add", "CS102", "Other")
        self.ok("instructor", "add", "E1", "jdoe", "Jane", "Doe", stdin="pw\n")
        self.ok("instructor", "assign", "E1", "CS101")
        self.ok("student", "add", "S1", "alice", "Alice", "Smith", stdin="pw\n")
        self.ok("student", "add", "S2", "bob", "Bob", "Lee", stdin="pw\n")


class LoginTests(CliTestCase):
    def test_fresh_database_only_allows_creating_first_admin(self):
        self.fails("course", "list", message="No admin account exists yet")
        self.ok("admin", "add", "A1", "root", "Ada", "Admin", stdin="pw\n")
        self.fails("course", "list", message="You are not logged in")
        # A second admin needs an admin to be logged in.
        self.fails("admin", "add", "A2", "eve", "Eve", "X", stdin="pw\n", message="not logged in")

    def test_login_whoami_logout(self):
        self.setup_school()
        self.assertIn("Logged in as Jane Doe (instructor)", self.login("jdoe"))
        self.assertIn("jdoe: Jane Doe (instructor)", self.ok("whoami"))
        self.assertIn("Logged out", self.ok("logout"))
        self.fails("whoami", message="not logged in")

    def test_wrong_password_and_unknown_user_give_same_error(self):
        self.setup_school()
        wrong = self.fails("login", "alice", stdin="nope\n")
        unknown = self.fails("login", "nobody", stdin="pw\n")
        self.assertEqual(wrong, unknown)
        self.assertIn("Invalid username or password", wrong)

    def test_session_token_not_stored_in_database(self):
        self.setup_school()
        with open(os.environ["CLASS_REG_SESSION_FILE"], encoding="utf-8") as f:
            token = next(iter(json.load(f).values()))
        with open(self.db, "rb") as f:
            self.assertNotIn(token.encode(), f.read())

    def test_deleted_session_logs_out(self):
        self.setup_school()
        os.remove(os.environ["CLASS_REG_SESSION_FILE"])
        self.fails("whoami", message="not logged in")

    def test_passwd_changes_password(self):
        self.setup_school()
        self.login("alice")
        self.fails("passwd", stdin="wrong\nnew\n", message="Current password is incorrect")
        self.ok("passwd", stdin="pw\nnewpw\n")
        self.ok("logout")
        self.fails("login", "alice", stdin="pw\n")
        self.login("alice", "newpw")

    def test_usernames_unique_across_roles(self):
        self.setup_school()
        self.fails(
            "student", "add", "S9", "jdoe", "Jo", "Doe", stdin="pw\n", message="already taken"
        )

    def test_empty_password_rejected(self):
        self.fails("admin", "add", "A1", "root", "A", "B", stdin="\n", message="must not be empty")


class AdminTests(CliTestCase):
    def test_full_registration_flow(self):
        self.setup_school()
        self.ok("init", "--max-credits", "10")
        self.assertIn("Enrolled S1", self.ok("register", "CS101", "--student", "S1"))
        self.assertIn("#1 on the waitlist", self.ok("register", "CS101", "--student", "S2"))
        out = self.ok("drop", "CS101", "--student", "S1")
        self.assertIn("Enrolled S2 from the waitlist", out)

        registrar = load_registrar(self.db)
        self.assertEqual(registrar.max_credits, 10)
        self.assertEqual([s.student_id for s in registrar.courses["CS101"].students], ["S2"])
        self.assertTrue(registrar.admins["A1"].check_password("pw"))

    def test_admin_must_name_student(self):
        self.setup_school()
        self.fails("register", "CS101", message="Use --student ID")

    def test_course_add_with_prereqs_and_meetings(self):
        self.setup_school()
        self.ok(
            "course", "add", "CS201", "Algorithms", "--prereq", "CS101", "--prereq", "MATH101",
            "--meets", "Mon 11:00-12:00", "--meets", "Wed 11:00-12:00",
        )  # fmt: skip
        out = self.ok("course", "show", "CS201")
        self.assertIn("Prerequisites: CS101, MATH101", out)
        self.assertIn("Meets:         Mon 11:00-12:00, Wed 11:00-12:00", out)

    def test_rule_violation_reports_error_and_saves_nothing(self):
        self.setup_school()
        self.ok("course", "add", "CS201", "Algorithms", "--prereq", "CS101")
        self.fails("register", "CS201", "--student", "S1", message="missing prerequisites")
        self.assertEqual(load_registrar(self.db).courses["CS201"].students, [])
        self.ok("student", "complete", "S1", "CS101")
        self.assertIn("Enrolled S1 in CS201", self.ok("register", "CS201", "--student", "S1"))

    def test_unknown_ids_are_errors(self):
        self.setup_school()
        self.fails("course", "show", "NOPE", message="No course")
        self.fails("student", "show", "S404", message="No student")
        self.fails("instructor", "assign", "E404", "CS101", message="No instructor")

    def test_duplicate_ids_rejected(self):
        self.setup_school()
        self.fails("student", "add", "S1", "eve", "Eve", "X", stdin="pw\n", message="exists")
        self.fails("course", "add", "CS101", "Again", message="already exists")
        self.fails("admin", "add", "A1", "eve", "Eve", "X", stdin="pw\n", message="exists")

    def test_bad_meeting_time_rejected(self):
        self.setup_school()
        self.fails("course", "add", "X", "Bad", "--meets", "Monday 9-10", message="invalid meeting")

    def test_admin_sees_roster_and_any_student(self):
        self.setup_school()
        self.ok("register", "CS101", "--student", "S1")
        self.assertIn("S1  Alice Smith", self.ok("course", "show", "CS101"))
        self.assertIn("S1: Alice Smith", self.ok("student", "show", "S1"))

    def test_course_list(self):
        self.setup_school()
        out = self.ok("course", "list")
        self.assertIn("CS101", out)
        self.assertIn("0/1", out)
        self.assertIn("Jane Doe", out)


class StudentTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.setup_school()
        self.login("alice")

    def test_student_registers_and_drops_self(self):
        self.assertIn("Enrolled S1 in CS101", self.ok("register", "CS101"))
        out = self.ok("student", "show")
        self.assertIn("S1: Alice Smith", out)
        self.assertIn("CS101  Intro (Mon 09:00-10:30)", out)
        self.assertIn("Dropped S1 from CS101", self.ok("drop", "CS101"))

    def test_student_cannot_act_for_others(self):
        self.fails("register", "CS101", "--student", "S2", message="only register themselves")
        self.fails("drop", "CS101", "--student", "S2", message="only drop their own")
        self.fails("student", "show", "S2", message="not allowed to view student S2")

    def test_student_sees_counts_not_names(self):
        self.ok("register", "CS101")
        out = self.ok("course", "show", "CS101")
        self.assertIn("Enrolled:      1", out)
        self.assertNotIn("Alice Smith", out)

    def test_student_cannot_use_admin_commands(self):
        for argv in (
            ("course", "add", "X", "X"),
            ("student", "add", "S9", "x", "X", "Y"),
            ("instructor", "assign", "E1", "CS102"),
            ("student", "complete", "S1", "CS101"),
            ("init", "--max-credits", "99"),
            ("admin", "add", "A2", "x", "X", "Y"),
        ):
            self.fails(*argv, stdin="pw\n", message="requires the")
        self.assertEqual(load_registrar(self.db).max_credits, 18)


class InstructorTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.setup_school()
        self.ok("register", "CS101", "--student", "S1")
        self.ok("register", "CS102", "--student", "S2")
        self.login("jdoe")

    def test_instructor_sees_own_roster_only(self):
        self.assertIn("S1  Alice Smith", self.ok("course", "show", "CS101"))
        out = self.ok("course", "show", "CS102")
        self.assertNotIn("Bob Lee", out)
        self.assertIn("Enrolled:      1", out)

    def test_instructor_views_own_students_only(self):
        self.assertIn("S1: Alice Smith", self.ok("student", "show", "S1"))
        self.fails("student", "show", "S2", message="not allowed")

    def test_instructor_records_completion_for_own_course_only(self):
        self.ok("student", "complete", "S1", "CS101")
        self.fails("student", "complete", "S1", "CS102", message="courses they teach")
        self.assertEqual(load_registrar(self.db).students["S1"].completed_courses, {"CS101"})

    def test_instructor_cannot_register_students(self):
        self.fails("register", "CS102", "--student", "S1", message="requires the admin or student")


class ReadOnlyTests(CliTestCase):
    def test_read_only_command_does_not_create_database(self):
        self.fails("course", "list", message="No admin account")
        self.assertFalse(os.path.exists(self.db))


if __name__ == "__main__":
    unittest.main()
