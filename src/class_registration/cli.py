"""Command-line interface: `class-reg --help`."""

import argparse
import getpass
import os
import sqlite3
import sys

from . import __version__
from .exceptions import RegistrationError
from .models import Instructor, MeetingTime, Student
from .registrar import WAITLISTED, Registrar
from .storage import load_registrar, save_registrar

DEFAULT_DB = "registration.db"


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


def _read_password():
    # Prompt without echo at a terminal; read one line when input is piped.
    if sys.stdin.isatty():
        password = getpass.getpass("Password: ")
    else:
        password = sys.stdin.readline().rstrip("\n")
    if not password:
        raise RegistrationError("Password must not be empty")
    return password


def _cmd_init(registrar, args):
    if args.max_credits is not None:
        if args.max_credits <= 0:
            raise RegistrationError("--max-credits must be positive")
        registrar.max_credits = args.max_credits
    print(f"Database {args.db} ready (max {registrar.max_credits} credits per student)")


def _cmd_course_add(registrar, args):
    meeting_times = [MeetingTime.parse(text) for text in args.meets]
    course = registrar.create_course(
        args.code,
        args.name,
        credits=args.credits,
        capacity=args.capacity,
        prerequisites=args.prereq,
        meeting_times=meeting_times,
    )
    print(f"Created {course.course_code}: {course.course_name}")


def _cmd_course_list(registrar, args):
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


def _cmd_course_show(registrar, args):
    course = _course(registrar, args.code)
    info = registrar.pull_course_registration_info(course)
    print(f"{course.course_code}: {course.course_name}")
    print(f"  Credits:       {course.credits}")
    print(f"  Capacity:      {'unlimited' if course.capacity is None else course.capacity}")
    print(f"  Instructor:    {info['Instructor'] or '-'}")
    print(f"  Prerequisites: {', '.join(sorted(course.prerequisites)) or '-'}")
    print(f"  Meets:         {', '.join(map(repr, course.meeting_times)) or '-'}")
    print(f"  Enrolled ({len(course.students)}):")
    for student in course.students:
        print(f"    {student.student_id}  {student.get_full_name()}")
    if course.waitlist:
        print(f"  Waitlist ({len(course.waitlist)}):")
        for position, student in enumerate(course.waitlist, start=1):
            print(f"    {position}. {student.student_id}  {student.get_full_name()}")


def _cmd_instructor_add(registrar, args):
    if args.employee_id in registrar.instructors:
        raise RegistrationError(f"Employee ID {args.employee_id} already exists")
    instructor = Instructor(
        args.username, _read_password(), args.first, args.last, args.employee_id
    )
    registrar.add_instructor(instructor)
    print(f"Added instructor {instructor.get_full_name()} ({instructor.employee_id})")


def _cmd_instructor_assign(registrar, args):
    instructor = _instructor(registrar, args.employee_id)
    course = _course(registrar, args.code)
    registrar.assign_instructor(course, instructor)
    print(f"{instructor.get_full_name()} now teaches {course.course_code}")


def _cmd_student_add(registrar, args):
    if args.student_id in registrar.students:
        raise RegistrationError(f"Student ID {args.student_id} already exists")
    student = Student(args.username, _read_password(), args.first, args.last, args.student_id)
    registrar.add_student(student)
    print(f"Added student {student.get_full_name()} ({student.student_id})")


def _cmd_student_complete(registrar, args):
    student = _student(registrar, args.student_id)
    for code in args.codes:
        student.complete_course(code)
    print(f"Recorded {', '.join(args.codes)} as completed for {student.student_id}")


def _cmd_student_show(registrar, args):
    student = _student(registrar, args.student_id)
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


def _cmd_register(registrar, args):
    student = _student(registrar, args.student_id)
    course = _course(registrar, args.code)
    status = registrar.register_student(student, course)
    if status == WAITLISTED:
        position = len(course.waitlist)
        print(f"{course.course_code} is full; {student.student_id} is #{position} on the waitlist")
    else:
        print(f"Enrolled {student.student_id} in {course.course_code}")


def _cmd_drop(registrar, args):
    student = _student(registrar, args.student_id)
    course = _course(registrar, args.code)
    promoted = registrar.drop_student(student, course)
    print(f"Dropped {student.student_id} from {course.course_code}")
    if promoted is not None:
        print(f"Enrolled {promoted.student_id} from the waitlist")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="class-reg", description="Manage courses, instructors and student registrations."
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

    p = command(commands, "init", _cmd_init, "create the database or change its settings")
    p.add_argument("--max-credits", type=int, help="credit limit per student")

    course = commands.add_parser("course", help="add, list and show courses")
    course_cmds = course.add_subparsers(dest="action", required=True, metavar="ACTION")
    p = command(course_cmds, "add", _cmd_course_add, "create a course")
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
        course_cmds, "show", _cmd_course_show, "show a course's details and class list", saves=False
    )
    p.add_argument("code")

    instructor = commands.add_parser("instructor", help="add and assign instructors")
    instructor_cmds = instructor.add_subparsers(dest="action", required=True, metavar="ACTION")
    p = command(
        instructor_cmds, "add", _cmd_instructor_add, "add an instructor (prompts for a password)"
    )
    p.add_argument("employee_id")
    p.add_argument("username")
    p.add_argument("first")
    p.add_argument("last")
    p = command(
        instructor_cmds, "assign", _cmd_instructor_assign, "assign an instructor to a course"
    )
    p.add_argument("employee_id")
    p.add_argument("code")

    student = commands.add_parser("student", help="add students and view their schedules")
    student_cmds = student.add_subparsers(dest="action", required=True, metavar="ACTION")
    p = command(student_cmds, "add", _cmd_student_add, "add a student (prompts for a password)")
    p.add_argument("student_id")
    p.add_argument("username")
    p.add_argument("first")
    p.add_argument("last")
    p = command(
        student_cmds, "complete", _cmd_student_complete, "record courses a student has completed"
    )
    p.add_argument("student_id")
    p.add_argument("codes", nargs="+", metavar="code")
    p = command(student_cmds, "show", _cmd_student_show, "show a student's schedule", saves=False)
    p.add_argument("student_id")

    p = command(
        commands, "register", _cmd_register, "register a student for a course (waitlists if full)"
    )
    p.add_argument("student_id")
    p.add_argument("code")
    p = command(commands, "drop", _cmd_drop, "drop a student from a course or its waitlist")
    p.add_argument("student_id")
    p.add_argument("code")

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.saves or os.path.exists(args.db):
            registrar = load_registrar(args.db)
        else:
            registrar = Registrar()  # don't create a file just to read it
        args.func(registrar, args)
        if args.saves:
            save_registrar(registrar, args.db)
    except (RegistrationError, ValueError, sqlite3.Error) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0
