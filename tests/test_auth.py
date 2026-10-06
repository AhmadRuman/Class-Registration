import os
import sqlite3
import tempfile
import unittest
from contextlib import closing

from class_registration import (
    ADMIN,
    INSTRUCTOR,
    STUDENT,
    Admin,
    AuthenticationError,
    Instructor,
    PermissionDenied,
    Registrar,
    RegistrationError,
    Student,
    User,
    authenticate,
    load_registrar,
    role_of,
    save_registrar,
)
from class_registration.auth import (
    can_manage_registration,
    can_record_completion,
    can_view_roster,
    can_view_student,
    require_role,
)
from class_registration.storage import (
    create_session,
    end_session,
    end_user_sessions,
    session_username,
)

# Keep password hashing cheap so the suite runs fast.
User.hash_iterations = 1_000


def make_school():
    registrar = Registrar()
    admin = Admin("root", "adminpw", "Ada", "Admin", "A1")
    teacher = Instructor("jdoe", "teachpw", "Jane", "Doe", "E1")
    other_teacher = Instructor("other", "pw", "Otto", "Other", "E2")
    alice = Student("alice", "alicepw", "Alice", "Smith", "S1")
    bob = Student("bob", "bobpw", "Bob", "Lee", "S2")
    registrar.add_admin(admin)
    cs101 = registrar.create_course("CS101", "Intro")
    cs102 = registrar.create_course("CS102", "Other")
    registrar.assign_instructor(cs101, teacher)
    registrar.assign_instructor(cs102, other_teacher)
    registrar.register_student(alice, cs101)
    registrar.register_student(bob, cs102)
    return registrar, admin, teacher, alice, bob, cs101, cs102


class AuthenticateTests(unittest.TestCase):
    def setUp(self):
        self.registrar, self.admin, self.teacher, self.alice, *_ = make_school()

    def test_valid_credentials_return_user(self):
        self.assertIs(authenticate(self.registrar, "jdoe", "teachpw"), self.teacher)
        self.assertIs(authenticate(self.registrar, "root", "adminpw"), self.admin)

    def test_wrong_password_and_unknown_user_rejected_alike(self):
        with self.assertRaisesRegex(AuthenticationError, "Invalid username or password"):
            authenticate(self.registrar, "jdoe", "wrong")
        with self.assertRaisesRegex(AuthenticationError, "Invalid username or password"):
            authenticate(self.registrar, "nobody", "teachpw")

    def test_roles(self):
        self.assertEqual(role_of(self.admin), ADMIN)
        self.assertEqual(role_of(self.teacher), INSTRUCTOR)
        self.assertEqual(role_of(self.alice), STUDENT)

    def test_require_role(self):
        require_role(self.admin, ADMIN)
        with self.assertRaises(PermissionDenied):
            require_role(self.alice, ADMIN, INSTRUCTOR)
        with self.assertRaises(AuthenticationError):
            require_role(None, ADMIN)


class PermissionTests(unittest.TestCase):
    def setUp(self):
        (self.registrar, self.admin, self.teacher, self.alice, self.bob, self.cs101, self.cs102) = (
            make_school()
        )

    def test_roster_visible_to_admin_and_own_instructor(self):
        self.assertTrue(can_view_roster(self.admin, self.cs102))
        self.assertTrue(can_view_roster(self.teacher, self.cs101))
        self.assertFalse(can_view_roster(self.teacher, self.cs102))
        self.assertFalse(can_view_roster(self.alice, self.cs101))

    def test_student_visibility(self):
        self.assertTrue(can_view_student(self.admin, self.bob, self.registrar))
        self.assertTrue(can_view_student(self.alice, self.alice, self.registrar))
        self.assertFalse(can_view_student(self.alice, self.bob, self.registrar))
        self.assertTrue(can_view_student(self.teacher, self.alice, self.registrar))
        self.assertFalse(can_view_student(self.teacher, self.bob, self.registrar))

    def test_registration_management(self):
        self.assertTrue(can_manage_registration(self.admin, self.bob))
        self.assertTrue(can_manage_registration(self.alice, self.alice))
        self.assertFalse(can_manage_registration(self.alice, self.bob))
        self.assertFalse(can_manage_registration(self.teacher, self.alice))

    def test_recording_completions(self):
        self.assertTrue(can_record_completion(self.admin, ["ANY999"], self.registrar))
        self.assertTrue(can_record_completion(self.teacher, ["CS101"], self.registrar))
        self.assertFalse(can_record_completion(self.teacher, ["CS101", "CS102"], self.registrar))
        self.assertFalse(can_record_completion(self.alice, ["CS101"], self.registrar))


class UsernameTests(unittest.TestCase):
    def test_usernames_unique_across_roles(self):
        registrar, *_ = make_school()
        with self.assertRaisesRegex(RegistrationError, "already taken"):
            registrar.add_student(Student("jdoe", "pw", "J", "D", "S9"))
        with self.assertRaisesRegex(RegistrationError, "already taken"):
            registrar.add_instructor(Instructor("alice", "pw", "A", "S", "E9"))
        with self.assertRaisesRegex(RegistrationError, "already taken"):
            registrar.add_admin(Admin("bob", "pw", "B", "L", "A9"))

    def test_taken_username_blocks_registration(self):
        registrar, *_, cs101, _ = make_school()
        with self.assertRaisesRegex(RegistrationError, "already taken"):
            registrar.register_student(Student("root", "pw", "R", "T", "S9"), cs101)

    def test_find_user(self):
        registrar, admin, teacher, alice, *_ = make_school()
        self.assertIs(registrar.find_user("root"), admin)
        self.assertIs(registrar.find_user("alice"), alice)
        self.assertIsNone(registrar.find_user("nobody"))


class SessionStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = os.path.join(self.tmpdir.name, "school.db")

    def test_session_round_trip_and_end(self):
        token = create_session(self.path, "alice", now=1000)
        self.assertEqual(session_username(self.path, token, now=1001), "alice")
        self.assertIsNone(session_username(self.path, "not-a-token", now=1001))
        end_session(self.path, token)
        self.assertIsNone(session_username(self.path, token, now=1001))

    def test_session_expires(self):
        token = create_session(self.path, "alice", lifetime=60, now=1000)
        self.assertEqual(session_username(self.path, token, now=1059), "alice")
        self.assertIsNone(session_username(self.path, token, now=1060))

    def test_end_user_sessions_keeps_current(self):
        keep = create_session(self.path, "alice", now=1000)
        other = create_session(self.path, "alice", now=1000)
        bob = create_session(self.path, "bob", now=1000)
        end_user_sessions(self.path, "alice", keep_token=keep)
        self.assertEqual(session_username(self.path, keep, now=1001), "alice")
        self.assertIsNone(session_username(self.path, other, now=1001))
        self.assertEqual(session_username(self.path, bob, now=1001), "bob")

    def test_saving_registrar_keeps_sessions(self):
        token = create_session(self.path, "root", now=1000)
        registrar, *_ = make_school()
        save_registrar(registrar, self.path)
        self.assertEqual(session_username(self.path, token, now=1001), "root")

    def test_admins_round_trip(self):
        registrar, *_ = make_school()
        save_registrar(registrar, self.path)
        loaded = load_registrar(self.path)
        self.assertTrue(loaded.admins["A1"].check_password("adminpw"))
        self.assertIs(loaded.find_user("root"), loaded.admins["A1"])

    def test_version_1_database_upgrades(self):
        # A file written by version 0.1: no admins or sessions tables.
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.executescript(
                """
                CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO settings VALUES ('max_credits', '12');
                PRAGMA user_version = 1;
                """
            )
        loaded = load_registrar(self.path)
        self.assertEqual(loaded.max_credits, 12)
        self.assertEqual(loaded.admins, {})
        create_session(self.path, "root")
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
