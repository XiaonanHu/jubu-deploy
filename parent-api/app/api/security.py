"""
Security utilities for authentication and authorization.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Union

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt  # PyJWT instead of jose
from passlib.context import CryptContext
from pydantic import ValidationError

from app_backend.app.core.config import settings
from app_backend.app.schemas.token import TokenPayload
from jubu_datastore import DatastoreFactory, User, UserDatastore
from jubu_datastore.common.exceptions import UserDataError
from jubu_datastore.logging import get_logger

logger = get_logger(__name__)

# Placeholder email for demo users. Must satisfy jubu_datastore User model (Pydantic EmailStr):
# - domain must contain a period; .local and other reserved/special-use TLDs are rejected by email-validator.
# - example.org is RFC 2606 reserved for documentation and is accepted by email-validator.
DEMO_PLACEHOLDER_EMAIL = "demo-parent@example.org"

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify if the provided password matches the hashed password."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Generate a password hash using bcrypt."""
    return pwd_context.hash(password)


def create_access_token(
    data: Dict[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token.
    
    Args:
        data: Data to encode in the token
        expires_delta: Optional expiration time
        
    Returns:
        JWT token string
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    # PyJWT may return bytes in some versions, ensure we return a string
    if isinstance(encoded_jwt, bytes):
        return encoded_jwt.decode('utf-8')
    return encoded_jwt


def get_user_datastore() -> UserDatastore:
    """Get the user datastore."""
    return DatastoreFactory.create_user_datastore()


def authenticate_user(email: str, password: str) -> Optional[User]:
    """
    Authenticate a user by email and password.
    
    Args:
        email: User's email
        password: User's password
        
    Returns:
        User object if authentication succeeds, None otherwise
    """
    user_datastore = get_user_datastore()
    user = user_datastore.get_by_email(email)
    
    if not user:
        return None
    
    if not verify_password(password, user.hashed_password or ""):
        return None
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    
    return user


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """
    Get the current authenticated user from the JWT token.
    
    Args:
        token: JWT token
        
    Returns:
        User object
        
    Raises:
        HTTPException: If authentication fails
    """
    logger.info(f"Authenticating user with token: {token[:10]}...")
    try:
        # Log the token verification attempt
        logger.info(f"Attempting to decode token with SECRET_KEY: {settings.SECRET_KEY[:5]}... and algorithm: {settings.JWT_ALGORITHM}")
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        logger.info(f"Token decoded successfully. Payload: {payload}")
        
        token_data = TokenPayload(**payload)
        logger.info(f"Token data validated: {token_data}")
        
        # PyJWT doesn't automatically check expiration, we need to do it manually
        if 'exp' in payload:
            exp_datetime = datetime.fromtimestamp(payload['exp'])
            now = datetime.now()
            logger.info(f"Token expiration: {exp_datetime}, Current time: {now}")
            
            if exp_datetime < now:
                logger.warning(f"Token expired at {exp_datetime}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token expired",
                    headers={"WWW-Authenticate": "Bearer"},
                )
    except (jwt.PyJWTError, ValidationError) as e:
        logger.error(f"Token validation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get the user from the database
    user_datastore = get_user_datastore()
    if settings.DEMO_MODE and settings.DEMO_PARENT_ID:
        # In demo mode we always act as the fixed demo parent; never use email lookup or overwrite DB with another parent.
        try:
            user = user_datastore.get(settings.DEMO_PARENT_ID)
        except UserDataError as e:
            # Row may exist with an invalid email (e.g. @local or @
            #  rejected by EmailStr).
            # Fix by updating to a validator-acceptable placeholder (see DEMO_PLACEHOLDER_EMAIL).
            err_msg = str(e).lower()
            if "email" in err_msg and "not valid" in err_msg:
                try:
                    user_datastore.update(settings.DEMO_PARENT_ID, {"email": DEMO_PLACEHOLDER_EMAIL})
                    user = user_datastore.get(settings.DEMO_PARENT_ID)
                    logger.info("Demo mode: corrected demo parent user email in DB (was invalid)")
                except Exception as fix_err:
                    logger.warning(f"Demo mode: could not fix demo parent email: {fix_err}")
                    raise
            else:
                raise
        if not user:
            # Demo parent may exist in profiles (e.g. from jubu_backend script) but not in users table; create a minimal user row so auth works.
            # Use the email they logged in with (token sub) only if it passes EmailStr (e.g. user@domain.com); else use validator-safe placeholder.
            _raw = token_data.sub or ""
            _domain = _raw.split("@")[-1] if "@" in _raw else ""
            _email = token_data.sub if ("@" in _raw and "." in _domain and not _domain.endswith(".local")) else DEMO_PLACEHOLDER_EMAIL
            try:
                user = user_datastore.create({
                    "id": settings.DEMO_PARENT_ID,
                    "email": _email,
                    "full_name": "Demo Parent",
                    "hashed_password": get_password_hash("demo"),
                })
                logger.info(f"Demo mode: created demo parent user {user.id} (was missing in users table)")
            except Exception as e:
                user = user_datastore.get(settings.DEMO_PARENT_ID)  # maybe another request just created it
                if not user:
                    logger.error(f"DEMO_PARENT_ID={settings.DEMO_PARENT_ID} not in DB and auto-create failed: {e}")
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Demo mode: DEMO_PARENT_ID user not found and could not be created. Ensure the DB is writable and .env is correct.",
                    )
        logger.info(f"Demo mode: acting as fixed parent {user.id}")
        return user
    logger.info(f"Looking up user with email: {token_data.sub}")
    user = user_datastore.get_by_email(token_data.sub)
    if not user:
        logger.warning(f"User with email {token_data.sub} not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    logger.info(f"User authenticated successfully: {user.id}")
    return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """
    Get the current active user.
    
    Args:
        current_user: Current user from token
        
    Returns:
        User object if active
        
    Raises:
        HTTPException: If user is inactive
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    
    return current_user