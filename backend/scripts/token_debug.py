#!/usr/bin/env python
"""
Debug script for validating JWT tokens.

Useful for tokens issued by the parent app backend (e.g. in jubu_parent_app repo).
Set SECRET_KEY and optionally JWT_ALGORITHM in the environment to verify signatures.

Usage:
    SECRET_KEY=your-secret python token_debug.py <token>
    python token_debug.py <token>   # decodes without verification if SECRET_KEY unset
"""

import os
import sys
from datetime import datetime

import jwt

from infrastructure.logging import get_logger

logger = get_logger(__name__)

# Read from env so this script works without app_backend (parent app backend is in another repo)
SECRET_KEY = os.environ.get("SECRET_KEY", "")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")


def decode_token(token: str):
    """Decode a JWT token and print its contents."""
    try:
        if not SECRET_KEY:
            logger.warning("SECRET_KEY not set; decoding without verification")
            payload = jwt.decode(token, options={"verify_signature": False})
            return False, payload

        # First, try to decode with verification
        logger.info("Attempting to decode token with verification")
        logger.info(f"SECRET_KEY: {SECRET_KEY[:5]}...")
        logger.info(f"JWT_ALGORITHM: {JWT_ALGORITHM}")

        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        logger.info(f"Token decoded successfully with verification")
        logger.info(f"Payload: {payload}")

        # Check expiration
        if "exp" in payload:
            exp_datetime = datetime.fromtimestamp(payload["exp"])
            now = datetime.now()
            logger.info(f"Token expiration: {exp_datetime}, Current time: {now}")
            if exp_datetime < now:
                logger.warning(f"Token has expired")
            else:
                logger.info(
                    f"Token is valid for {(exp_datetime - now).total_seconds()} more seconds"
                )

        # Check subject
        if "sub" in payload:
            logger.info(f"Token subject (user email): {payload['sub']}")

        return True, payload

    except Exception as e:
        logger.error(f"Error decoding token with verification: {str(e)}")

        # Try to decode without verification to see what's in the token
        try:
            logger.info(f"Attempting to decode token without verification")
            payload = jwt.decode(token, options={"verify_signature": False})
            logger.info(f"Token decoded without verification: {payload}")
            return False, payload
        except Exception as e2:
            logger.error(f"Error decoding token without verification: {str(e2)}")
            return False, None


def main():
    """Main function to parse and decode token."""
    if len(sys.argv) < 2:
        print("Usage: python token_debug.py <token>")
        return

    token = sys.argv[1]
    print(f"Analyzing token: {token[:10]}...")

    valid, payload = decode_token(token)

    if valid:
        print("✅ Token is valid!")
    else:
        print("❌ Token is invalid!")

    if payload:
        print("\nToken payload:")
        for key, value in payload.items():
            print(f"  {key}: {value}")

            if key == "exp":
                exp_datetime = datetime.fromtimestamp(value)
                now = datetime.now()
                print(
                    f"  Expiration: {exp_datetime} ({'expired' if exp_datetime < now else 'valid'})"
                )


if __name__ == "__main__":
    main()
