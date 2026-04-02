"""
Main application file for KidsChat Parent App Backend.
"""

import time
import uvicorn
import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app_backend.app.api.auth import router as auth_router
from app_backend.app.api.profiles import router as profiles_router
from app_backend.app.api.conversations import router as conversations_router
from app_backend.app.api.config import router as config_router
from app_backend.app.api.users import router as users_router
from app_backend.app.core.config import settings
from jubu_datastore.logging import get_logger

logger = get_logger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="API for parent interaction with KidsChat system",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add request logging middleware
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Log the request
        logger.info(
            f"Request {request.method} {request.url.path} started"
        )
        
        # Log auth header if present
        auth_header = request.headers.get("Authorization")
        if auth_header:
            logger.info(f"Auth header present: {auth_header[:15]}...")
        else:
            logger.warning(f"No Authorization header in request to {request.url.path}")
        
        try:
            response = await call_next(request)
            
            # Log the response status
            process_time = time.time() - start_time
            logger.info(
                f"Request {request.method} {request.url.path} completed with status {response.status_code} in {process_time:.3f}s"
            )
            
            # Log more details for auth failures
            if response.status_code == 401:
                logger.warning(f"Authentication failed for request to {request.url.path}")
                
            return response
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(
                f"Request {request.method} {request.url.path} failed in {process_time:.3f}s: {str(e)}",
                exc_info=True
            )
            raise

app.add_middleware(RequestLoggingMiddleware)


@app.on_event("startup")
def on_startup():
    """Set env so jubu_datastore uses app_backend DB config."""
    import os
    os.environ["DATABASE_URL"] = settings.DATABASE_URI
    os.environ["DB_POOL_SIZE"] = str(settings.DATABASE_POOL_SIZE)
    logger.info("Set DATABASE_URL and DB_POOL_SIZE for jubu_datastore")
    if settings.DEMO_MODE:
        msg = "DEMO_MODE is ON: login accepts any email/password (for local demos only)"
        if settings.DEMO_PARENT_ID:
            msg += f"; all requests act as fixed parent {settings.DEMO_PARENT_ID}"
        logger.warning(msg)


# Include routers
app.include_router(auth_router, prefix=f"{settings.API_V1_STR}/auth", tags=["authentication"])
app.include_router(profiles_router, prefix=f"{settings.API_V1_STR}/profiles", tags=["profiles"])
app.include_router(conversations_router, prefix=f"{settings.API_V1_STR}/conversations", tags=["conversations"])
app.include_router(config_router, prefix=f"{settings.API_V1_STR}/config", tags=["configuration"])
app.include_router(users_router, prefix=f"{settings.API_V1_STR}/users", tags=["users"])

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

@app.get("/")
def root():
    """Root endpoint for health check."""
    return {"message": "KidsChat Parent API is running"}

# Debug route for authentication testing
@app.get("/api/debug/auth-test")
async def debug_auth_test(request: Request):
    """Debug endpoint to test authentication."""
    auth_header = request.headers.get("Authorization")
    logger.info(f"Debug Auth Test - Auth header: {auth_header[:15] if auth_header else 'None'}")
    
    # Check token format if present
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "")
        logger.info(f"Debug Auth Test - Token: {token[:10]}...")
    
    return {
        "auth_header": auth_header is not None,
        "token_format_valid": token is not None,
        "request_id": str(id(request)),
        "timestamp": str(datetime.datetime.now())
    }

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred"}
    )

# Tables are created by jubu_datastore when datastores are first instantiated.

if __name__ == "__main__":
    uvicorn.run("app_backend.main:app", host="0.0.0.0", port=8000, reload=True)