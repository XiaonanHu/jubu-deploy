# KidsChat Parent App Backend

## Overview

This backend service provides API access to the KidsChat system for parent applications. It connects to the same datastores as the main KidsChat system but provides a parent-focused interface for managing child profiles, viewing conversation history, and configuring system settings.

## Architecture

- **Framework**: FastAPI
- **Authentication**: JWT token-based authentication
- **Database Access**: Uses existing KidsChat datastores
- **API Structure**: RESTful endpoints organized by domain

## Key Features

- Parent account management
- Child profile management
- Conversation history access and search
- Fact extraction review
- Parental controls and settings
- Story library access

## Getting Started

### Prerequisites
- Python 3.9+
- Access to KidsChat datastores

### Installation

```bash
pip install -r requirements.txt
uvicorn app_backend.main:app --reload
```

### Configuration

Create a `.env` file in the **project root** (same directory as `app_backend/`) with:

```
DATABASE_URI=your_database_connection_string
SECRET_KEY=your_secret_key
JWT_TOKEN_EXPIRE_MINUTES=10080
```

**Demo mode (accept any email/password at login)**  
Set `DEMO_MODE=true` in `.env`. When enabled, the login endpoint accepts any email and any password: if the email exists, it logs in as that user (password ignored); if not, it creates a user with that email and a placeholder password, then logs in. Use only for local demos; do not enable in production.

**Demo child and parent (fixed for demos)**  
When `DEMO_MODE=true` set both:

- `DEMO_PARENT_ID=<uuid>` — the user id that owns the demo child in the DB (e.g. the parent in jubu_backend). Every authenticated request is treated as this parent: profiles and conversations are loaded via `get_profiles_by_parent(DEMO_PARENT_ID)` and the same datastore APIs you use in scripts.
- `DEMO_CHILD_ID=<uuid>` — the child whose conversations the app shows; the app uses this as the default child when loading conversations. If that parent has no profile with this id yet, the backend creates a "Demo Child" profile for them.

With both set, the backend does not inject or special-case the demo child; it just uses the fixed parent id and pulls everything from the datastore accordingly.

If the demo parent user is missing in the `users` table, the backend auto-creates one. The stored email must pass Pydantic `EmailStr` (email-validator): the domain must contain a period, and reserved/special-use TLDs (e.g. `.local`) are rejected. The backend uses `demo-parent@example.org` (RFC 2606 documentation domain) when a placeholder is needed. If you have an existing row with an invalid email, either delete it so the next request recreates it, or run: `UPDATE users SET email = 'demo-parent@example.org' WHERE id = '<DEMO_PARENT_ID>';`.

## API Documentation

Once running, visit `/docs` for full Swagger documentation.

## Security Considerations

- All endpoints require authentication except for registration and login
- JWT tokens expire after 7 days by default
- Sensitive operations require re-authentication
- All API traffic should be encrypted with TLS


