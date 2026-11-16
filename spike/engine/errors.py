"""Engine errors. Each carries a user-safe message. See docs/CONTRACT.md section 7."""


class EngineError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class IngestError(EngineError):
    """The file cannot be read, or has no data."""


class PlanError(EngineError):
    """The user's decisions do not match the profile's proposals."""
