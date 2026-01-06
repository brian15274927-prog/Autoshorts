"""
API Exceptions and Error Handlers.
"""
from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Any


class ErrorResponse(BaseModel):
    """Standard error response format."""
    error: str
    detail: Optional[str] = None
    code: str
    status_code: int


class APIError(Exception):
    """Base API exception."""

    def __init__(
        self,
        message: str,
        code: str = "API_ERROR",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail: Optional[str] = None,
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)

    def to_response(self) -> ErrorResponse:
        return ErrorResponse(
            error=self.message,
            detail=self.detail,
            code=self.code,
            status_code=self.status_code,
        )


class ValidationError(APIError):
    """400 - Bad Request / Validation Error."""

    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )


class NotFoundError(APIError):
    """404 - Resource Not Found."""

    def __init__(self, resource: str, resource_id: str):
        super().__init__(
            message=f"{resource} not found: {resource_id}",
            code="NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class TaskNotFoundError(NotFoundError):
    """404 - Task Not Found."""

    def __init__(self, task_id: str):
        super().__init__(resource="Task", resource_id=task_id)


class InternalError(APIError):
    """500 - Internal Server Error."""

    def __init__(self, message: str = "Internal server error", detail: Optional[str] = None):
        super().__init__(
            message=message,
            code="INTERNAL_ERROR",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        )


class ServiceUnavailableError(APIError):
    """503 - Service Unavailable."""

    def __init__(self, service: str = "Rendering service"):
        super().__init__(
            message=f"{service} is temporarily unavailable",
            code="SERVICE_UNAVAILABLE",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Handle APIError exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_response().model_dump(),
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "detail": str(exc) if request.app.debug else None,
            "code": "INTERNAL_ERROR",
            "status_code": 500,
        },
    )
