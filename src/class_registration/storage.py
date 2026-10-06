"""Save and load a Registrar to and from a SQLite database file."""

import hashlib
import secrets
import sqlite3
import time as clock
from contextlib import closing
from datetime import time

from .models import Admin, Course, Instructor, MeetingTime, Student
from .registrar import Registrar

# Version 2 added the admins and sessions tables. Older files are upgraded in
# place on open: every table is created only if it is missing.
SCHEMA_VERSION = 2
SUPPORTED_VERSIONS = (0, 1, 2)

SESSION_LIFETIME = 8 * 60 * 60  # seconds

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS students (
    student_id    TEXT PRIMARY KEY,
    username      TEXT NOT NULL,
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    salt          BLOB,
    password_hash BLOB,
    iterations    INTEGER
);
CREATE TABLE IF NOT EXISTS completed_courses (
    student_id  TEXT NOT NULL REFERENCES students(student_id),
    course_code TEXT NOT NULL,
    PRIMARY KEY (student_id, course_code)
);
CREATE TABLE IF NOT EXISTS instructors (
    employee_id   TEXT PRIMARY KEY,
    username      TEXT NOT NULL,
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    salt          BLOB,
    password_hash BLOB,
    iterations    INTEGER
);
CREATE TABLE IF NOT EXISTS admins (
    admin_id      TEXT PRIMARY KEY,
    username      TEXT NOT NULL,
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    salt          BLOB,
    password_hash BLOB,
    iterations    INTEGER
);
CREATE TABLE IF NOT EXISTS courses (
    course_code   TEXT PRIMARY KEY,
    course_name   TEXT NOT NULL,
    credits       INTEGER NOT NULL,
    capacity      INTEGER,
    instructor_id TEXT REFERENCES instructors(employee_id)
);
CREATE TABLE IF NOT EXISTS prerequisites (
    course_code  TEXT NOT NULL REFERENCES courses(course_code),
    prerequisite TEXT NOT NULL,
    PRIMARY KEY (course_code, prerequisite)
);
CREATE TABLE IF NOT EXISTS meeting_times (
    course_code TEXT NOT NULL REFERENCES courses(course_code),
    day         TEXT NOT NULL,
    start_time  TEXT NOT NULL,
    end_time    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS enrollments (
    course_code TEXT NOT NULL REFERENCES courses(course_code),
    student_id  TEXT NOT NULL REFERENCES students(student_id),
    position    INTEGER NOT NULL,
    PRIMARY KEY (course_code, student_id)
);
CREATE TABLE IF NOT EXISTS waitlist (
    course_code TEXT NOT NULL REFERENCES courses(course_code),
    student_id  TEXT NOT NULL REFERENCES students(student_id),
    position    INTEGER NOT NULL,
    PRIMARY KEY (course_code, student_id)
);
-- Login sessions are not part of the Registrar's state, so save_registrar
-- leaves this table alone. Only a hash of each token is stored.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    username   TEXT NOT NULL,
    expires_at REAL NOT NULL
);
"""

# Children before parents, so deletes never violate a foreign key.
TABLES = (
    "enrollments",
    "waitlist",
    "meeting_times",
    "prerequisites",
    "courses",
    "completed_courses",
    "students",
    "instructors",
    "admins",
    "settings",
)


def _connect(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version not in SUPPORTED_VERSIONS:
        conn.close()
        raise ValueError(
            f"{path} uses schema version {version}; this program supports {SCHEMA_VERSION}"
        )
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return conn


def _user_row(user):
    return (
        user.username,
        user.first_name,
        user.last_name,
        user._salt,
        user._password_hash,
        user._iterations,
    )


def _restore_password(user, salt, password_hash, iterations):
    user._salt = salt
    user._password_hash = password_hash
    user._iterations = iterations


def save_registrar(registrar, path):
    """Write the registrar's full state to path, replacing what was there.

    The write is one transaction: if anything fails, the file keeps its
    previous contents.
    """
    with closing(_connect(path)) as conn, conn:
        for table in TABLES:
            conn.execute(f"DELETE FROM {table}")

        conn.execute(
            "INSERT INTO settings VALUES ('max_credits', ?)", (str(registrar.max_credits),)
        )
        for student in registrar.students.values():
            conn.execute(
                "INSERT INTO students VALUES (?, ?, ?, ?, ?, ?, ?)",
                (student.student_id, *_user_row(student)),
            )
            conn.executemany(
                "INSERT INTO completed_courses VALUES (?, ?)",
                [(student.student_id, code) for code in sorted(student.completed_courses)],
            )
        for instructor in registrar.instructors.values():
            conn.execute(
                "INSERT INTO instructors VALUES (?, ?, ?, ?, ?, ?, ?)",
                (instructor.employee_id, *_user_row(instructor)),
            )
        for admin in registrar.admins.values():
            conn.execute(
                "INSERT INTO admins VALUES (?, ?, ?, ?, ?, ?, ?)",
                (admin.admin_id, *_user_row(admin)),
            )
        for course in registrar.courses.values():
            conn.execute(
                "INSERT INTO courses VALUES (?, ?, ?, ?, ?)",
                (
                    course.course_code,
                    course.course_name,
                    course.credits,
                    course.capacity,
                    course.instructor.employee_id if course.instructor else None,
                ),
            )
            conn.executemany(
                "INSERT INTO prerequisites VALUES (?, ?)",
                [(course.course_code, code) for code in sorted(course.prerequisites)],
            )
            conn.executemany(
                "INSERT INTO meeting_times VALUES (?, ?, ?, ?)",
                [
                    (course.course_code, mt.day, mt.start.isoformat(), mt.end.isoformat())
                    for mt in course.meeting_times
                ],
            )
            conn.executemany(
                "INSERT INTO enrollments VALUES (?, ?, ?)",
                [(course.course_code, s.student_id, i) for i, s in enumerate(course.students)],
            )
            conn.executemany(
                "INSERT INTO waitlist VALUES (?, ?, ?)",
                [(course.course_code, s.student_id, i) for i, s in enumerate(course.waitlist)],
            )


def load_registrar(path):
    """Rebuild a Registrar from a file written by save_registrar.

    A file that does not exist yet loads as an empty Registrar.
    """
    with closing(_connect(path)) as conn:
        settings = dict(conn.execute("SELECT key, value FROM settings"))
        registrar = Registrar(max_credits=int(settings.get("max_credits", 18)))

        for student_id, username, first, last, salt, pw_hash, iters in conn.execute(
            "SELECT * FROM students"
        ):
            student = Student(username, None, first, last, student_id)
            _restore_password(student, salt, pw_hash, iters)
            registrar.students[student_id] = student
        for student_id, code in conn.execute("SELECT * FROM completed_courses"):
            registrar.students[student_id].complete_course(code)

        for employee_id, username, first, last, salt, pw_hash, iters in conn.execute(
            "SELECT * FROM instructors"
        ):
            instructor = Instructor(username, None, first, last, employee_id)
            _restore_password(instructor, salt, pw_hash, iters)
            registrar.instructors[employee_id] = instructor

        for admin_id, username, first, last, salt, pw_hash, iters in conn.execute(
            "SELECT * FROM admins"
        ):
            admin = Admin(username, None, first, last, admin_id)
            _restore_password(admin, salt, pw_hash, iters)
            registrar.admins[admin_id] = admin

        prereqs = {}
        for code, prereq in conn.execute("SELECT * FROM prerequisites"):
            prereqs.setdefault(code, []).append(prereq)
        meetings = {}
        for code, day, start, end in conn.execute("SELECT * FROM meeting_times ORDER BY rowid"):
            meetings.setdefault(code, []).append(
                MeetingTime(day, time.fromisoformat(start), time.fromisoformat(end))
            )

        for code, name, credits, capacity, instructor_id in conn.execute("SELECT * FROM courses"):
            course = Course(
                code,
                name,
                credits=credits,
                capacity=capacity,
                prerequisites=prereqs.get(code, ()),
                meeting_times=meetings.get(code, ()),
            )
            if instructor_id is not None:
                course.instructor = registrar.instructors[instructor_id]
            registrar.courses[code] = course

        # Restore rosters exactly as saved rather than re-running registration
        # checks, which could reject students if the rules changed since.
        for code, student_id, _ in conn.execute(
            "SELECT * FROM enrollments ORDER BY course_code, position"
        ):
            registrar.courses[code].students.append(registrar.students[student_id])
        for code, student_id, _ in conn.execute(
            "SELECT * FROM waitlist ORDER BY course_code, position"
        ):
            registrar.courses[code].waitlist.append(registrar.students[student_id])

    return registrar


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(path, username, lifetime=SESSION_LIFETIME, now=None):
    """Start a login session for username and return its secret token."""
    now = clock.time() if now is None else now
    token = secrets.token_urlsafe(32)
    with closing(_connect(path)) as conn, conn:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?, ?)", (_token_hash(token), username, now + lifetime)
        )
    return token


def session_username(path, token, now=None):
    """Return the username a live session token belongs to, or None."""
    now = clock.time() if now is None else now
    with closing(_connect(path)) as conn:
        row = conn.execute(
            "SELECT username FROM sessions WHERE token_hash = ? AND expires_at > ?",
            (_token_hash(token), now),
        ).fetchone()
    return row[0] if row else None


def end_session(path, token):
    with closing(_connect(path)) as conn, conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def end_user_sessions(path, username, keep_token=None):
    """End all of a user's sessions, except keep_token's if given."""
    keep = _token_hash(keep_token) if keep_token else ""
    with closing(_connect(path)) as conn, conn:
        conn.execute(
            "DELETE FROM sessions WHERE username = ? AND token_hash != ?", (username, keep)
        )
