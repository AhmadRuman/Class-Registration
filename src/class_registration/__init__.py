"""A class registration system: courses, instructors, students and enrollment rules."""

from .exceptions import RegistrationError
from .models import DAYS, Course, Instructor, MeetingTime, Student, User
from .registrar import ENROLLED, WAITLISTED, Registrar
from .storage import load_registrar, save_registrar

__version__ = "0.1.0"

__all__ = [
    "DAYS",
    "ENROLLED",
    "WAITLISTED",
    "Course",
    "Instructor",
    "MeetingTime",
    "Registrar",
    "RegistrationError",
    "Student",
    "User",
    "load_registrar",
    "save_registrar",
]
