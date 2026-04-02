"""
Utility functions for API endpoints.
"""

from fastapi import HTTPException, status
from jubu_datastore.common.exceptions import (
    DatastoreError,
    ProfileDataError,
    ConversationDataError,
)

def handle_datastore_error(e: Exception, operation: str) -> HTTPException:
    """Convert datastore exceptions to appropriate HTTP exceptions."""
    if isinstance(e, (ProfileDataError, ConversationDataError)):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    elif isinstance(e, DatastoreError):
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error during {operation}: {str(e)}"
        )
    else:
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error during {operation}: {str(e)}"
        ) 