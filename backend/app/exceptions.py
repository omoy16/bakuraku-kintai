"""Service errors, independent of HTTP responses."""


class AttendanceConflictError(Exception):
    """The requested punch cannot be applied to the current attendance state."""


class AttendanceNotFoundError(Exception):
    """The current user cannot access a record with the requested ID."""


class DatabaseUnavailableError(Exception):
    """The configured database cannot be opened, queried, or committed."""
