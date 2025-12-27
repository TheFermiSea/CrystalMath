"""Custom exceptions for Materials API operations."""

from __future__ import annotations


class MaterialsAPIError(Exception):
    """Base exception for Materials API errors."""

    def __init__(self, message: str, source: str | None = None) -> None:
        """Initialize error with message and optional source.

        Args:
            message: Error description
            source: API source ('mp', 'mpcontribs', 'optimade')
        """
        self.source = source
        super().__init__(message)


class AuthenticationError(MaterialsAPIError):
    """Raised when API authentication fails."""

    def __init__(self, source: str, message: str | None = None) -> None:
        msg = message or f"Authentication failed for {source}. Check your API key."
        super().__init__(msg, source=source)


class RateLimitError(MaterialsAPIError):
    """Raised when API rate limit is exceeded."""

    def __init__(
        self,
        source: str,
        retry_after: int | None = None,
        message: str | None = None
    ) -> None:
        """Initialize rate limit error.

        Args:
            source: API source
            retry_after: Seconds to wait before retrying
            message: Optional custom message
        """
        self.retry_after = retry_after
        msg = message or f"Rate limit exceeded for {source}."
        if retry_after:
            msg += f" Retry after {retry_after} seconds."
        super().__init__(msg, source=source)


class StructureNotFoundError(MaterialsAPIError):
    """Raised when a requested structure is not found."""

    def __init__(
        self,
        identifier: str,
        source: str | None = None,
        message: str | None = None
    ) -> None:
        """Initialize not found error.

        Args:
            identifier: Material ID or formula searched
            source: API source searched
            message: Optional custom message
        """
        self.identifier = identifier
        msg = message or f"Structure not found: {identifier}"
        if source:
            msg += f" (searched {source})"
        super().__init__(msg, source=source)


class NetworkError(MaterialsAPIError):
    """Raised on network connectivity issues."""

    def __init__(self, source: str, original_error: Exception | None = None) -> None:
        """Initialize network error.

        Args:
            source: API source
            original_error: Underlying exception
        """
        self.original_error = original_error
        msg = f"Network error connecting to {source}"
        if original_error:
            msg += f": {original_error}"
        super().__init__(msg, source=source)


class CacheError(MaterialsAPIError):
    """Raised on cache read/write failures."""

    def __init__(self, operation: str, message: str | None = None) -> None:
        """Initialize cache error.

        Args:
            operation: Cache operation that failed ('read', 'write', 'expire')
            message: Optional details
        """
        self.operation = operation
        msg = message or f"Cache {operation} failed"
        super().__init__(msg)


class ValidationError(MaterialsAPIError):
    """Raised when API response validation fails."""

    def __init__(self, field: str, message: str | None = None) -> None:
        """Initialize validation error.

        Args:
            field: Field that failed validation
            message: Validation details
        """
        self.field = field
        msg = message or f"Validation failed for field: {field}"
        super().__init__(msg)
