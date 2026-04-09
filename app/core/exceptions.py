from fastapi import Request, status
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger("core")

class APIError(Exception):
    """
    Базовый класс для кастомных ошибок API.
    """
    def __init__(self, message: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR, details: dict = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)

class ExternalAPIError(APIError):
    """
    Ошибка при обращении к внешним API (Gemini, ElevenLabs).
    """
    def __init__(self, message: str, service_name: str, details: dict = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_502_BAD_GATEWAY,
            details={"service": service_name, **(details or {})}
        )

class NotFoundError(APIError):
    """
    Ошибка, когда запрашиваемый ресурс не найден.
    """
    def __init__(self, message: str, details: dict = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            details=details
        )

class ValidationError(APIError):
    """
    Ошибка валидации входных данных.
    """
    def __init__(self, message: str, details: dict = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details
        )

async def api_error_handler(request: Request, exc: APIError):
    """
    Глобальный перехватчик для всех кастомных APIError.
    """
    logger.error(f"API Error: {exc.message} (Status: {exc.status_code}, Details: {exc.details})")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": exc.message,
            "details": exc.details
        }
    )

async def global_exception_handler(request: Request, exc: Exception):
    """
    Перехватчик для всех остальных необработанных исключений (500).
    """
    logger.exception(f"Unhandled Exception: {str(exc)}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": "Внутренняя ошибка сервера",
            "details": {"type": exc.__class__.__name__, "msg": str(exc)}
        }
    )
