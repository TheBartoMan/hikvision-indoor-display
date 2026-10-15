"""Errors with fixed, credential-free messages."""


class StationError(Exception):
    """Station command or protocol failure."""


class AuthenticationError(StationError):
    """SSH authentication was rejected."""


class ConnectionFailure(StationError):
    """Connection, timeout, or host verification failure."""


class UnsupportedFirmware(StationError):
    """The running binary is not a verified compatible firmware."""


class BusyStation(StationError):
    """Another operation or an unsafe screen prevents control."""
