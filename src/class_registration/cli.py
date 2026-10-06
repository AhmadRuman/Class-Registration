"""Command-line interface: `class-reg --help`."""

import argparse
import getpass
import json
import os
import sqlite3
import sys

from . import __version__
from .auth import (
    ADMIN,
    INSTRUCTOR,
    STUDENT,
    authenticate,
    can_manage_registration,
    can_record_completion,
    can_view_roster,
    can_view_student,
    require_role,
    role_of,
)
from .exceptions import AuthenticationError, PermissionDenied, RegistrationError
from .models import Admin, Instructor, MeetingTime, Student
from .registrar import WAITLISTED, Registrar
from .storage import (
    create_session,
    end_session,
    end_user_sessions,
    load_registrar,
    save_registrar,
    session_username,
)

DEFAULT_DB = "registration.db"
ANY_ROLE = (ADMIN, INSTRUCTOR, STUDENT)


class Context:
    def __init__(self, db, registrar, user, token):
        self.db = db
        self.registrar = registrar
        self.user = user
        self.token = token

    def require(self, *roles):
        if self.user is None:
            if not self.registrar.admins:
                raise AuthenticationError(
                    "No admin account exists yet; create one with `class-reg admin add`"
                )
            raise AuthenticationError("You are not logged in; run `class-reg login USERNAME`")
        require_role(self.user, *roles)


# --- Login sessions -------------------------------------------------------
# The token for each database lives in a per-user file, keyed by the
# database's absolute path. The database only stores a hash of it.


def _session_file():
    return os.environ.get("CLASS_REG_SESSION_FILE") or os.path.join(
        os.path.expanduser("~"), ".class_reg_session"
    )


def _read_tokens():
    try:
        with open(_session_file(), encoding="utf-8") as f:
            tokens = json.load(f)
    except (OSError, ValueError):
        return {}
    return tokens if isinstance(tokens, dict) else {}


def _write_token(db, token):
    tokens = _read_tokens()
    key = os.path.abspath(db)
    if token is None:
        tokens.pop(key, None)
    else:
        tokens[key] = token
    path = _session_file()
    # Create the file readable by its owner only.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with open(fd, "w", encoding="utf-8") as f:
        json.dump(tokens, f)


def _logged_in_user(db, registrar):
    token = _read_tokens().get(os.path.abspath(db))
    if token is None:
        return None, None
    username = session_username(db, token)
    user = registrar.find_user(username) if username else None
    return (user, token) if user else (None, None)


# --- Helpers --------------------------------------------------------------


def _course(registrar, code):
    try:
        return registrar.courses[code]
    except KeyError:
        raise RegistrationError(f"No course with code {code}") from None


def _student(registrar, student_id):
    try:
        return registrar.students[student_id]
    except KeyError:
        raise RegistrationError(f"No student with ID {student_id}") from None


def _instructor(registrar, employee_id):
    try:
        return registrar.instructors[employee_id]
    except KeyError:
        raise RegistrationError(f"No instructor with employee ID {employee_id}") from None


def _read_password(prompt="Password: "):
    # Prompt without echo at a terminal; read one line when input is piped.
    if sys.stdin.isatty():
        password = getpass.getpass(prompt)
    else:
        password = sys.stdin.readline().rstrip("\n")
    if not password:
        raise RegistrationError("Password must not be empty")
    return password


def _read_new_password(prompt="New password: "):
    password = _read_password(prompt)
    if sys.stdin.isatty() and getpass.getpass("Repeat password: ") != password:
        raise RegistrationError("Passwords do not match")
    return password


def _target_student(ctx, student_id):
    """The student a command acts on: --student for staff, yourself for students."""
    if student_id is None:
        if role_of(ctx.user) != STUDENT:
            raise RegistrationError("Use --student ID to say which student")
        return ctx.user
    return _student(ctx.registrar, student_id)


# --- Account commands -----------------------------------------------------


def _cmd_login(ctx, args):
    user = authenticate(ctx.registrar, args.username, _read_password())
    token = create_session(ctx.db, user.username)
    if ctx.token is not None:
        end_session(ctx.db, ctx.token)
    _write_token(ctx.db, token)
    print(f"Logged in as {user.get_full_name()} ({role_of(user)})")


def _cmd_logout(ctx, args):
    if ctx.token is None:
        print("Not logged in")
        return
    end_session(ctx.db, ctx.token)
    _write_token(ctx.db, None)
    print("Logged out")


def _cmd_whoami(ctx, args):
    ctx.require(*ANY_ROLE)
    print(f"{ctx.user.username}: {ctx.user.get_full_name()} ({role_of(ctx.user)})")


def _cmd_passwd(ctx, args):
    ctx.require(*ANY_ROLE)
    if not ctx.user.check_password(_read_password("Current password: ")):
        raise AuthenticationError("Current password is incorrect")
    ctx.user.set_password(_read_new_password())
    # Changing a password signs out every other session for this account.
    end_user_sessions(ctx.db, ctx.user.username, keep_token=ctx.token)
    print("Password changed")


def _cmd_admin_add(ctx, args):
    if ctx.registrar.admins:
        ctx.require(ADMIN)
    if args.admin_id in ctx.registrar.admins:
        raise RegistrationError(f"Admin ID {args.admin_id} already exists")
    admin = Admin(args.username, _read_new_password(), args.first, args.last, args.admin_id)
    ctx.registrar.add_admin(admin)
    print(f"Added admin {admin.get_full_name()} ({admin.admin_id})")


# --- Registrar commands ---------------------------------------------------


def _cmd_init(ctx, args):
    ctx.require(ADMIN)
    if args.max_credits is not None:
        if args.max_credits <= 0:
            raise RegistrationError("--max-credits must be positive")
        ctx.registrar.max_credits = args.max_credits
    print(f"Database {ctx.db} ready (max {ctx.registrar.max_credits} credits per student)")


def _cmd_course_add(ctx, args):
    ctx.require(ADMIN)
    meeting_times = [MeetingTime.parse(text) for text in args.meets]
    course = ctx.registrar.create_course(
        args.code,
        args.name,
        credits=args.credits,
        capacity=args.capacity,
        prerequisites=args.prereq,
        meeting_times=meeting_times,
    )
    print(f"Created {course.course_code}: {course.course_name}")


def _cmd_course_list(ctx, args):
    ctx.require(*ANY_ROLE)
    registrar = ctx.registrar
    if not registrar.courses:
        print("No courses yet")
        return
    print(f"{'CODE':<10} {'NAME':<30} {'CREDITS':>7} {'SEATS':>9} {'WAITLIST':>8}  INSTRUCTOR")
    for course in sorted(registrar.courses.values(), key=lambda c: c.course_code):
        capacity = "-" if course.capacity is None else course.capacity
        seats = f"{len(course.students)}/{capacity}"
        instructor = course.instructor.get_full_name() if course.instructor else "-"
        print(
            f"{course.course_code:<10} {course.course_name:<30} {course.credits:>7} "
            f"{seats:>9} {len(course.waitlist):>8}  {instructor}"
        )


def _cmd_course_show(ctx, args):
    ctx.require(*ANY_ROLE)
    course = _course(ctx.registrar, args.code)
    info = ctx.registrar.pull_course_registration_info(course)
    print(f"{course.course_code}: {course.course_name}")
    print(f"  Credits:       {course.credits}")
    print(f"  Capacity:      {'unlimited' if course.capacity is None else course.capacity}")
    print(f"  Instructor:    {info['Instructor'] or '-'}")
    print(f"  Prerequisites: {', '.join(sorted(course.prerequisites)) or '-'}")
    print(f"  Meets:         {', '.join(map(repr, course.meeting_times)) or '-'}")
    if not can_view_roster(ctx.user, course):
        # Students and other instructors see counts, not names.
        print(f"  Enrolled:      {len(course.students)}")
        print(f"  Waitlist:      {len(course.waitlist)}")
        return
    print(f"  Enrolled ({len(course.students)}):")
    for student in course.students:
        print(f"    {student.student_id}  {student.get_full_name()}")
    if course.waitlist:
        print(f"  Waitlist ({len(course.waitlist)}):")
        for position, student in enumerate(course.waitlist, start=1):
            print(f"    {position}. {student.student_id}  {student.get_full_name()}")


def _cmd_instructor_add(ctx, args):
    ctx.require(ADMIN)
    if args.employee_id in ctx.registrar.instructors:
        raise RegistrationError(f"Employee ID {args.employee_id} already exists")
    instructor = Instructor(
        args.username, _read_new_password(), args.first, args.last, args.employee_id
    )
    ctx.registrar.add_instructor(instructor)
    print(f"Added instructor {instructor.get_full_name()} ({instructor.employee_id})")


def _cmd_instructor_assign(ctx, args):
    ctx.require(ADMIN)
    instructor = _instructor(ctx.registrar, args.employee_id)
    course = _course(ctx.registrar, args.code)
    ctx.registrar.assign_instructor(course, instructor)
    print(f"{instructor.get_full_name()} now teaches {course.course_code}")


def _cmd_student_add(ctx, args):
    ctx.require(ADMIN)
    if args.student_id in ctx.registrar.students:
        raise RegistrationError(f"Student ID {args.student_id} already exists")
    student = Student(args.username, _read_new_password(), args.first, args.last, args.student_id)
    ctx.registrar.add_student(student)
    print(f"Added student {student.get_full_name()} ({student.student_id})")


def _cmd_student_complete(ctx, args):
    ctx.require(ADMIN, INSTRUCTOR)
    student = _student(ctx.registrar, args.student_id)
    if not can_record_completion(ctx.user, args.codes, ctx.registrar):
        raise PermissionDenied("Instructors can only record completions for courses they teach")
    for code in args.codes:
        student.complete_course(code)
    print(f"Recorded {', '.join(args.codes)} as completed for {student.student_id}")


def _cmd_student_show(ctx, args):
    ctx.require(*ANY_ROLE)
    registrar = ctx.registrar
    student = _target_student(ctx, args.student_id)
    if not can_view_student(ctx.user, student, registrar):
        raise PermissionDenied(f"You are not allowed to view student {student.student_id}")
    courses = registrar.get_student_courses(student)
    waitlisted = [c for c in registrar.courses.values() if student in c.waitlist]
    print(f"{student.student_id}: {student.get_full_name()} ({student.username})")
    print(f"  Credits:   {registrar.get_student_credits(student)}/{registrar.max_credits}")
    print(f"  Completed: {', '.join(sorted(student.completed_courses)) or '-'}")
    print("  Enrolled:")
    for course in sorted(courses, key=lambda c: c.course_code):
        meets = ", ".join(map(repr, course.meeting_times)) or "no set times"
        print(f"    {course.course_code}  {course.course_name} ({meets})")
    if not courses:
        print("    -")
    if waitlisted:
        print("  Waitlisted:")
        for course in sorted(waitlisted, key=lambda c: c.course_code):
            position = course.waitlist.index(student) + 1
            print(f"    {course.course_code}  position {position}")


def _cmd_register(ctx, args):
    ctx.require(ADMIN, STUDENT)
    student = _target_student(ctx, args.student)
    if not can_manage_registration(ctx.user, student):
        raise PermissionDenied("Students can only register themselves")
    course = _course(ctx.registrar, args.code)
    status = ctx.registrar.register_student(student, course)
    if status == WAITLISTED:
        position = len(course.waitlist)
        print(f"{course.course_code} is full; {student.student_id} is #{position} on the waitlist")
    else:
        print(f"Enrolled {student.student_id} in {course.course_code}")


def _cmd_drop(ctx, args):
    ctx.require(ADMIN, STUDENT)
    student = _target_student(ctx, args.student)
    if not can_manage_registration(ctx.user, student):
        raise PermissionDenied("Students can only drop their own courses")
    course = _course(ctx.registrar, args.code)
    promoted = ctx.registrar.drop_student(student, course)
    print(f"Dropped {student.student_id} from {course.course_code}")
    if promoted is not None:
        print(f"Enrolled {promoted.student_id} from the waitlist")


# --- Argument parsing -----------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        prog="class-reg",
        description="Manage courses, instructors and student registrations.",
        epilog="Start with `class-reg admin add` to create the first admin, "
        "then `class-reg login`.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--db",
        default=os.environ.get("CLASS_REG_DB", DEFAULT_DB),
        help=f"SQLite database file (default: $CLASS_REG_DB or {DEFAULT_DB})",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def command(subparsers, name, func, help, saves=True):
        p = subparsers.add_parser(name, help=help, description=help)
        p.set_defaults(func=func, saves=saves)
        return p

    def person_args(p, id_name):
        p.add_argument(id_name)
        p.add_argument("username")
        p.add_argument("first")
        p.add_argument("last")

    p = command(commands, "login", _cmd_login, "log in (prompts for a password)", saves=False)
    p.add_argument("username")
    command(commands, "logout", _cmd_logout, "log out", saves=False)
    command(commands, "whoami", _cmd_whoami, "show who is logged in", saves=False)
    command(commands, "passwd", _cmd_passwd, "change your password")

    admin = commands.add_parser("admin", help="manage admin accounts")
    admin_cmds = admin.add_subparsers(dest="action", required=True, metavar="ACTION")
    p = command(
        admin_cmds,
        "add",
        _cmd_admin_add,
        "add an admin (prompts for a password); allowed without login for the first admin",
    )
    person_args(p, "admin_id")

    p = command(commands, "init", _cmd_init, "change database settings (admin)")
    p.add_argument("--max-credits", type=int, help="credit limit per student")

    course = commands.add_parser("course", help="add, list and show courses")
    course_cmds = course.add_subparsers(dest="action", required=True, metavar="ACTION")
    p = command(course_cmds, "add", _cmd_course_add, "create a course (admin)")
    p.add_argument("code")
    p.add_argument("name")
    p.add_argument("--credits", type=int, default=3, help="default: 3")
    p.add_argument("--capacity", type=int, help="seat limit (default: unlimited)")
    p.add_argument(
        "--prereq",
        action="append",
        default=[],
        metavar="CODE",
        help="required completed course; repeat for several",
    )
    p.add_argument(
        "--meets",
        action="append",
        default=[],
        metavar="'DAY HH:MM-HH:MM'",
        help="meeting time such as 'Mon 09:00-10:30'; repeat for several",
    )
    command(course_cmds, "list", _cmd_course_list, "list all courses", saves=False)
    p = command(
        course_cmds,
        "show",
        _cmd_course_show,
        "show a course's details (class list for admins and its instructor)",
        saves=False,
    )
    p.add_argument("code")

    instructor = commands.add_parser("instructor", help="add and assign instructors")
    instructor_cmds = instructor.add_subparsers(dest="action", required=True, metavar="ACTION")
    p = command(
        instructor_cmds,
        "add",
        _cmd_instructor_add,
        "add an instructor (admin; prompts for a password)",
    )
    person_args(p, "employee_id")
    p = command(
        instructor_cmds,
        "assign",
        _cmd_instructor_assign,
        "assign an instructor to a course (admin)",
    )
    p.add_argument("employee_id")
    p.add_argument("code")

    student = commands.add_parser("student", help="add students and view their schedules")
    student_cmds = student.add_subparsers(dest="action", required=True, metavar="ACTION")
    p = command(
        student_cmds, "add", _cmd_student_add, "add a student (admin; prompts for a password)"
    )
    person_args(p, "student_id")
    p = command(
        student_cmds,
        "complete",
        _cmd_student_complete,
        "record completed courses (admin, or the instructor of those courses)",
    )
    p.add_argument("student_id")
    p.add_argument("codes", nargs="+", metavar="code")
    p = command(
        student_cmds,
        "show",
        _cmd_student_show,
        "show a student's schedule (yours if you are a student)",
        saves=False,
    )
    p.add_argument("student_id", nargs="?")

    p = command(
        commands,
        "register",
        _cmd_register,
        "register for a course, or join its waitlist if full",
    )
    p.add_argument("code")
    p.add_argument("--student", metavar="ID", help="student to register (admins only)")
    p = command(commands, "drop", _cmd_drop, "drop a course or leave its waitlist")
    p.add_argument("code")
    p.add_argument("--student", metavar="ID", help="student to drop (admins only)")

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        exists = os.path.exists(args.db)
        if args.saves or exists:
            registrar = load_registrar(args.db)
        else:
            registrar = Registrar()  # don't create a file just to read it
        user, token = _logged_in_user(args.db, registrar) if exists else (None, None)
        args.func(Context(args.db, registrar, user, token), args)
        if args.saves:
            save_registrar(registrar, args.db)
    except (RegistrationError, ValueError, sqlite3.Error) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0
