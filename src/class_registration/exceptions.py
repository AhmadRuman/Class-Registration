class RegistrationError(Exception):
    """Raised when a registrar operation is not allowed."""


class AuthenticationError(RegistrationError):
    """Raised when a login fails or no one is logged in."""


class PermissionDenied(RegistrationError):
    """Raised when the logged-in user's role does not allow an action."""
