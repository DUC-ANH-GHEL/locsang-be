from fastapi import HTTPException, status

class BaseAppException(Exception):
    """Base exception for all application exceptions"""
    def __init__(self, message: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

class NotFoundException(Exception):
    """Raised when a resource is not found"""
    pass

class ValidationException(Exception):
    """Raised when validation fails"""
    pass

class AuthenticationException(Exception):
    """Raised when authentication fails"""
    pass

class AuthorizationException(Exception):
    """Raised when authorization fails"""
    pass

class DatabaseException(Exception):
    """Raised when a database operation fails"""
    pass
