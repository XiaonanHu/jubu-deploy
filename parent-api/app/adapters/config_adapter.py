"""
Adapter for configuration operations.
"""

from typing import Dict, Any, Optional

from fastapi import HTTPException, status

from app_backend.app.core.config import settings

class ConfigAdapter:
    """Adapter for configuration operations."""
    
    def get_public_config(self) -> Dict[str, Any]:
        """
        Get public configuration settings.
        
        Returns:
            Public configuration settings
        """
        return {
            "project_name": settings.PROJECT_NAME,
            "api_version": "v1",
            "cors_origins": settings.CORS_ORIGINS
        }
    
    def get_feature_flags(self) -> Dict[str, bool]:
        """
        Get feature flags.
        
        Returns:
            Feature flags
        """
        # This could be expanded to load from a database or external service
        return {
            "enable_chat_history": True,
            "enable_fact_extraction": True,
            "enable_parent_controls": True
        } 