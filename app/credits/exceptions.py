"""
Credit-related exceptions.
"""
from fastapi import HTTPException, status


class CreditError(Exception):
    """Base credit error."""

    def __init__(self, message: str, code: str = "CREDIT_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class InsufficientCreditsError(CreditError):
    """Raised when user doesn't have enough credits."""

    def __init__(self, user_id: str, required: int = 1, available: int = 0):
        self.user_id = user_id
        self.required = required
        self.available = available
        super().__init__(
            message=f"Insufficient credits: required={required}, available={available}",
            code="INSUFFICIENT_CREDITS",
        )

    def to_http_exception(self) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Insufficient credits",
                "code": self.code,
                "required": self.required,
                "available": self.available,
                "message": "Please upgrade your plan or purchase more credits",
            },
        )


class JobNotOwnedError(CreditError):
    """Raised when user tries to access job they don't own."""

    def __init__(self, user_id: str, task_id: str):
        self.user_id = user_id
        self.task_id = task_id
        super().__init__(
            message=f"User {user_id} does not own task {task_id}",
            code="JOB_NOT_OWNED",
        )

    def to_http_exception(self) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Access denied",
                "code": self.code,
                "message": "You do not have permission to access this render job",
            },
        )
