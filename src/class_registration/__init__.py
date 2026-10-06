"""A class registration system: courses, instructors, students and enrollment rules."""

from .auth import ADMIN, INSTRUCTOR, STUDENT, authenticate, role_of
from .exceptions import AuthenticationError, PermissionDenied, RegistrationError
from .models import DAYS, Admin, Course, Instructor, MeetingTime, Student, User
from .registrar import ENROLLED, WAITLISTED, Registrar
from .storage import load_registrar, save_registrar

__version__ = "0.2.0"

__all__ = [
    "ADMIN",
    "DAYS",
    "ENROLLED",
    "INSTRUCTOR",
    "STUDENT",
    "WAITLISTED",
    "Admin",
    "AuthenticationError",
    "Course",
    "Instructor",
    "MeetingTime",
    "PermissionDenied",
    "Registrar",
    "RegistrationError",
    "Student",
    "User",
    "authenticate",
    "load_registrar",
    "role_of",
    "save_registrar",
]
