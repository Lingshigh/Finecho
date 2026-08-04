class FinEchoError(Exception):
    """Base exception that can be safely converted into an API error."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(FinEchoError):
    status_code = 404
    code = "not_found"


class ConflictError(FinEchoError):
    status_code = 409
    code = "conflict"


class AnalysisError(FinEchoError):
    status_code = 422
    code = "analysis_failed"
