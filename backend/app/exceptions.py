"""Service errors, independent of HTTP responses."""


class AttendanceConflictError(Exception):
    """The requested punch cannot be applied to the current attendance state."""


class DatabaseUnavailableError(Exception):
    """The configured database cannot be opened, queried, or committed."""
