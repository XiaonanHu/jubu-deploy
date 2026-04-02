# KidsChat Parent API

This directory contains the backend API for the KidsChat Parent Portal, which allows parents to manage their children's profiles, view conversations, and access other features of the KidsChat platform.

## Directory Structure

The application follows a modular architecture with clear separation of concerns: 

app/
├── adapters/ # Interface adapters between API and datastores
├── api/ # API endpoints and route definitions
├── core/ # Core application components and configuration
└── schemas/ # Pydantic models for request/response validation


## API Layer (`api/`)

The API layer defines the HTTP endpoints that clients can interact with.

- **`auth.py`**: Authentication endpoints (register, login, password reset)
- **`conversations.py`**: Endpoints for retrieving and managing conversations
- **`deps.py`**: Dependency injection functions for datastores
- **`profiles.py`**: Endpoints for managing child profiles
- **`security.py`**: Security utilities for authentication and authorization

## Adapter Layer (`adapters/`)

The adapter layer connects the API endpoints to the KidsChat datastores.

- **`profile_adapter.py`**: Adapter for child profile operations
- **`conversation_adapter.py`**: Adapter for conversation operations
- **`user_adapter.py`**: Adapter for user account operations

## Core Layer (`core/`)

The core layer contains central application components and configuration.

- **`config.py`**: Application configuration settings using Pydantic

## Schemas Layer (`schemas/`)

The schemas layer defines Pydantic models for request/response validation and serialization.

- **`conversation.py`**: Schemas for conversation data
- **`profile.py`**: Schemas for child profile data
- **`token.py`**: Schemas for authentication tokens
- **`user.py`**: Schemas for user data

## Integration with KidsChat Datastores

This API integrates with the KidsChat datastores defined in `jubu_chat/chat/datastores/` to provide a secure interface for parents to access their children's data.

### Key Integrations:

1. **Profile Management**:
   - Uses `ProfileDatastore` to create, retrieve, update, and delete child profiles
   - Enforces parent-child relationships for security

2. **Conversation Access**:
   - Uses `ConversationDatastore` to retrieve conversations and conversation history
   - Implements proper authorization to ensure parents can only access their children's conversations

3. **Facts Retrieval**:
   - Uses `FactsDatastore` to retrieve facts extracted from conversations
   - Provides insights to parents about their children's interests and knowledge

## Authentication and Security

The API implements JWT-based authentication with the following features:

- Secure password hashing using bcrypt
- Token-based authentication with configurable expiration
- Role-based access control
- Proper error handling for authentication failures

## Error Handling

The API implements consistent error handling through adapter-specific error handlers, which convert datastore exceptions to appropriate HTTP responses.