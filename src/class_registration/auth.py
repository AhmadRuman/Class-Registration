"""Logging in and role-based permissions.

The Registrar itself enforces registration rules only; this module decides
who may ask it to do what.
"""

from .exceptions import AuthenticationError, PermissionDenied
from .models import Admin, Instructor, Student, User

ADMIN = "admin"
INSTRUCTOR = "instructor"
STUDENT = "student"

_dummy_user = None


def role_of(user):
    if isinstance(user, Admin):
        return ADMIN
    if isinstance(user, Instructor):
        return INSTRUCTOR
    if isinstance(user, Student):
        return STUDENT
    raise TypeError(f"unknown user type {type(user).__name__}")


def authenticate(registrar, username, password):
    """Return the user with these credentials, or raise AuthenticationError.

    Unknown usernames and wrong passwords give the same error, and both cost
    one password hash, so a failed login does not reveal which usernames exist.
    """
    global _dummy_user
    user = registrar.find_user(username)
    if user is None:
        if _dummy_user is None:
            _dummy_user = User("", "dummy password", "", "")
        _dummy_user.check_password(password)
    elif user.check_password(password):
        return user
    raise AuthenticationError("Invalid username or password")


def require_role(user, *roles):
    if user is None:
        raise AuthenticationError("You are not logged in")
    if role_of(user) not in roles:
        raise PermissionDenied(f"This action requires the {' or '.join(roles)} role")


def can_view_roster(user, course):
    """Admins see every class list; instructors see the ones they teach."""
    return role_of(user) == ADMIN or course.instructor is user


def can_view_student(user, student, registrar):
    """Admins see everyone, students see themselves, instructors see their own students."""
    role = role_of(user)
    if role == ADMIN or user is student:
        return True
    if role == INSTRUCTOR:
        return any(student in c.students for c in registrar.get_instructor_courses(user))
    return False


def can_manage_registration(user, student):
    """Admins can register or drop anyone; students only themselves."""
    return role_of(user) == ADMIN or user is student


def can_record_completion(user, course_codes, registrar):
    """Admins can record any course; instructors only courses they teach."""
    role = role_of(user)
    if role == ADMIN:
        return True
    if role == INSTRUCTOR:
        taught = {c.course_code for c in registrar.get_instructor_courses(user)}
        return set(course_codes) <= taught
    return False


__all__ = [
    "ADMIN",
    "INSTRUCTOR",
    "STUDENT",
    "PermissionDenied",
    "authenticate",
    "can_manage_registration",
    "can_record_completion",
    "can_view_roster",
    "can_view_student",
    "require_role",
    "role_of",
]
