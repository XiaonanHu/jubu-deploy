# KidsChat Datastore Architecture

This document outlines the datastore architecture for the KidsChat application, detailing the database schema, data models, and how the backend interacts with the datastore. **If you are building a parent app that shows live conversation or transcript:** the source of truth for the session transcript is the **conversations** and **conversation_turns** tables; see [How the backend interacts with the datastore](#how-the-backend-interacts-with-the-datastore) and [Reading data (for parent app or API)](#reading-data-for-parent-app-or-api).

## Overview

The KidsChat datastore is responsible for persisting conversation data, child profiles, facts about children, and other critical information. It follows domain-driven design principles with a focus on data security, privacy, and compliance with child data protection regulations.

## Implementation Details

The datastore layer is implemented using SQLAlchemy ORM with the following key components:

1. **BaseDatastore**: An abstract base class that provides common functionality such as connection management, transaction handling, and security features.

2. **Model Classes**: Each entity has a corresponding SQLAlchemy model class (e.g., `UserModel`, `ChildProfileModel`) that defines the database schema.

3. **Datastore Classes**: For each entity, there's a specialized datastore class (e.g., `UserDatastore`, `ProfileDatastore`) that handles CRUD operations and business logic.

4. **DatastoreFactory**: A factory class that manages the creation and lifecycle of datastore instances, providing singleton access when appropriate.

This architecture ensures clean separation between the domain model and persistence concerns, while providing type-safe and consistent access to the database.

## Database Tables

### 1. Users (User)
Stores information about parent/guardian user accounts that manage child profiles.

| Field | Type | Description |
|-------|------|-------------|
| id | String(36) | Primary key (UUID) |
| email | String(100) | User's email address (unique) |
| full_name | String(100) | User's full name |
| hashed_password | String(100) | Hashed password for authentication |
| is_active | Boolean | Whether the account is active (for soft deletion) |
| created_at | DateTime | When the account was created |
| updated_at | DateTime | When the account was last updated |

**Purpose**: Manages parent/guardian accounts that oversee child profiles, handling authentication and user management functions.

### 2. Child Profiles (ChildProfile)
Stores information about children using the application.

| Field | Type | Description |
|-------|------|-------------|
| id | String(36) | Primary key (UUID) |
| name | String(100) | Child's name |
| age | Integer | Child's age |
| interests | JSON Array | List of child's interests |
| preferences | JSON Object | Key-value pairs of preferences |
| created_at | DateTime | When the profile was created |
| updated_at | DateTime | When the profile was last updated |
| parent_id | String(36) | Reference to parent account (nullable) |
| is_active | Boolean | Whether the profile is active (for soft deletion) |
| last_interaction | DateTime | When the child last interacted with the system |

**Purpose**: Stores essential information about each child user, including their preferences and interests, to personalize interactions and comply with parental controls.

### 3. Conversations (Conversation)
Stores metadata about conversations.

| Field | Type | Description |
|-------|------|-------------|
| id | String(36) | Primary key (UUID) |
| child_id | String(36) | Reference to child profile |
| state | String(20) | Conversation state: `active`, `paused`, `ended`, or `flagged` (see `ConversationState` enum) |
| start_time | DateTime | When the conversation started |
| end_time | DateTime | When the conversation ended (nullable) |
| last_interaction_time | DateTime | When the last message was exchanged |
| conv_metadata | JSON Object | Additional conversation metadata (see below) |
| is_archived | Boolean | Whether the conversation is archived |

**conv_metadata** is a JSON object. The backend typically stores:
- `current_interaction_type`: string (e.g. `"chitchat"`).
- `parent_id`: string (UUID of the parent user), when available.

**Purpose**: Manages the lifecycle of conversations between children and the system, tracking conversation state and providing context for message exchanges.

### 4. Conversation Turns (ConversationTurn)
Stores individual messages in conversations.

| Field | Type | Description |
|-------|------|-------------|
| id | String(36) | Primary key (UUID) |
| conversation_id | String(36) | Reference to conversation |
| timestamp | DateTime | When the turn occurred |
| child_message | Text | Message from the child |
| system_message | Text | Response from the system |
| interaction_type | String(50) | Type of interaction (chitchat, pretend_play, etc.) |
| safety_evaluation | JSON Object | Safety evaluation results (see below) |

**safety_evaluation** is a JSON object written after the turn is created (often asynchronously). It can contain:
- `is_safe`: boolean
- `severity`: string — `"none"`, `"low"`, `"medium"`, or `"high"`
- `tags`: array of strings — e.g. `"personal_information"`, `"sensitive_topics"`, `"inappropriate_language"`, `"manipulation"`, `"emotional_distress"`
- `concerns`: array of strings (human-readable)
- `redact_turn`: boolean — when true, the backend replaces `child_message` with the literal placeholder `"[message redacted for safety]"` and persists that to the database so the parent app can show redacted content without storing the original.

**Purpose**: Records the back-and-forth exchanges between children and the system, enabling conversation history review and analysis of interaction quality. The parent app can use `safety_evaluation` and the possibly redacted `child_message` for compliance and display.

### 5. Child Facts (ChildFact)
Stores facts extracted about children during conversations.

| Field | Type | Description |
|-------|------|-------------|
| id | String(36) | Primary key (UUID) |
| child_id | String(36) | Reference to child profile |
| source_turn_id | String(36) | Reference to conversation turn where fact was extracted (nullable) |
| content | Text | The fact content |
| confidence | Float | Confidence score (0.0-1.0) |
| timestamp | DateTime | When the fact was extracted |
| expiration | DateTime | When the fact expires |
| verified | Boolean | Whether the fact has been verified |
| active | Boolean | Whether the fact is active |
| created_at | DateTime | When the fact was created |

**Purpose**: Collects and manages knowledge about children extracted from conversations, allowing the system to remember details and provide personalized interactions while maintaining data freshness through expiration dates.

**Note — Parental settings (e.g. prohibited topics) are not stored in a database table.** They are passed at runtime when starting a conversation (e.g. via `ConversationManager(parental_settings={...})`) and used only in memory for prompt construction. If a parent app needs to persist or display these, it must store them in its own layer or in `child_profiles`/app-backend user settings.

### 6. Interaction Contexts (InteractionContext)
Stores context information for specific interaction types.

| Field | Type | Description |
|-------|------|-------------|
| id | String(36) | Primary key (UUID) |
| conversation_id | String(36) | Reference to conversation |
| interaction_type | String(50) | Type of interaction |
| context_data | JSON Object | Context-specific data |
| created_at | DateTime | When the context was created |
| updated_at | DateTime | When the context was last updated |

**Purpose**: Maintains state for different types of interactions (storytelling, pretend play, education) across conversation sessions, enabling continuity of complex interactions.

### 7. Stories (Story)
Stores stories created during storytelling interactions.

| Field | Type | Description |
|-------|------|-------------|
| id | String(36) | Primary key (UUID) |
| child_id | String(36) | Reference to child profile |
| conversation_id | String(36) | Reference to conversation |
| title | String(200) | Story title |
| content | Text | Story content |
| created_at | DateTime | When the story was created |
| is_favorite | Boolean | Whether the story is marked as favorite |
| tags | JSON Array | Tags categorizing the story |
| last_viewed_at | DateTime | When the story was last viewed |

**Purpose**: Archives stories created during storytelling interactions, allowing children to revisit and enjoy their favorite stories, building a library of personalized content.

## Database Relationships

The KidsChat database uses a relational structure to connect different entities. Below are the key relationships:

1. **User to Child Profiles**: One-to-many relationship where a parent/guardian user can have multiple child profiles.
   - Foreign key: `parent_id` in `child_profiles` references `id` in `users`
   - Implemented as: `parent = relationship("User", back_populates="child_profiles")` and `child_profiles = relationship("ChildProfileModel", back_populates="parent")`

2. **Child Profile to Conversations**: One-to-many relationship where a child can have multiple conversations.
   - Foreign key: `child_id` in `conversations` references `id` in `child_profiles`

3. **Child Profile to Child Facts**: One-to-many relationship where multiple facts can be stored about a child.
   - Foreign key: `child_id` in `child_facts` references `id` in `child_profiles`

4. **Child Profile to Stories**: One-to-many relationship where a child can have multiple stories.
   - Foreign key: `child_id` in `stories` references `id` in `child_profiles`

5. **Conversation to Conversation Turns**: One-to-many relationship where a conversation consists of multiple turns.
   - Foreign key: `conversation_id` in `conversation_turns` references `id` in `conversations`
   - Implemented as: `conversation = relationship("ConversationModel", back_populates="turns")` and `turns = relationship("ConversationTurnModel", back_populates="conversation", cascade="all, delete-orphan")`

6. **Conversation to Interaction Contexts**: One-to-many relationship where a conversation can have multiple interaction contexts.
   - Foreign key: `conversation_id` in `interaction_contexts` references `id` in `conversations`

7. **Conversation to Stories**: One-to-many relationship where multiple stories can be created within a conversation.
   - Foreign key: `conversation_id` in `stories` references `id` in `conversations`

## Entity Relationship Diagram

Below is a textual representation of the entity relationships. For a visual diagram, you can use tools like [dbdiagram.io](https://dbdiagram.io), [Lucidchart](https://www.lucidchart.com), or [draw.io](https://draw.io) with the following schema definitions:

```
Table users {
  id String [pk]
  email String [unique]
  full_name String
  hashed_password String
  is_active Boolean
  created_at DateTime
  updated_at DateTime
}

Table child_profiles {
  id String [pk]
  name String
  age Integer
  interests JSON
  preferences JSON
  created_at DateTime
  updated_at DateTime
  parent_id String [ref: > users.id]
  is_active Boolean
  last_interaction DateTime
}

Table conversations {
  id String [pk]
  child_id String [ref: > child_profiles.id]
  state String
  start_time DateTime
  end_time DateTime
  last_interaction_time DateTime
  conv_metadata JSON
  is_archived Boolean
}

Table conversation_turns {
  id String [pk]
  conversation_id String [ref: > conversations.id]
  timestamp DateTime
  child_message Text
  system_message Text
  interaction_type String
  safety_evaluation JSON
}

Table child_facts {
  id String [pk]
  child_id String [ref: > child_profiles.id]
  source_turn_id String
  content Text
  confidence Float
  timestamp DateTime
  expiration DateTime
  verified Boolean
  active Boolean
  created_at DateTime
}

Table interaction_contexts {
  id String [pk]
  conversation_id String [ref: > conversations.id]
  interaction_type String
  context_data JSON
  created_at DateTime
  updated_at DateTime
}

Table stories {
  id String [pk]
  child_id String [ref: > child_profiles.id]
  conversation_id String [ref: > conversations.id]
  title String
  content Text
  created_at DateTime
  is_favorite Boolean
  tags JSON
  last_viewed_at DateTime
}
```

## How the backend interacts with the datastore

This section describes **who writes to the datastore, when, and with what guarantees**. It is important for a parent app that reads the same database or API: you can rely on the data only when writes have succeeded, and some data is never persisted from the conversation flow.

### Who writes and when

- **ConversationManager** (used by the voice/LiveKit pipeline) uses the same datastores and writes:
  - **Conversations**: On session start, it creates a row via `conversation_datastore.create(...)` with `id`, `child_id`, `state`, `start_time`, `last_interaction_time`, `conv_metadata`. On state change (e.g. ended, flagged) it calls `conversation_datastore.update(conversation_id, {"state": ..., "end_time": ...})`.
  - **Conversation turns**: After each assistant response, it calls `conversation_datastore.add_conversation_turn(conversation_id, turn_data)` with `id`, `conversation_id`, `timestamp`, `child_message`, `system_message`, `interaction_type`, and optionally `safety_evaluation`. Later, when safety evaluation completes (possibly asynchronously), it may call `conversation_datastore.update_conversation_turn(conversation_id, turn_id, {"safety_evaluation": ..., "child_message": ...})` to store safety tags and/or the redacted `child_message`.
  - **Child profiles**: On first use it may create or update a profile via `profile_datastore.create(...)` or `profile_datastore.update(...)` (e.g. name, interests). Profile creation/update can also happen when the system infers the child’s name.
- **App backend (FastAPI)** uses the same datastores (via `DatastoreFactory.get_datastore(...)`). It mainly **reads** (conversations, turns, profiles, facts). It **writes** when the parent archives a conversation (`conversation_datastore.update(..., {"is_archived": True})`), or when creating/updating profiles via the parent API.

### Persistence guarantees

- Writes from ConversationManager are wrapped in try/except: on failure the error is logged and the process continues. So **conversations, turns, and profile updates are best-effort** — the DB may be missing the latest conversation or turn if a write failed. A parent app that polls or subscribes to this store should tolerate missing or delayed rows.
- **Facts** and **interaction contexts** are **not** persisted from the conversation flow. ConversationManager loads them when restoring a session (`facts_datastore.get_active_facts_for_child`, `interaction_contexts_datastore.get_context_for_conversation`) but does not call `save_child_fact` or `save_interaction_context` during the live conversation. So for “live” transcript and session state, the source of truth is **conversations** and **conversation_turns** (and optionally **child_profiles**).

### Summary for parent app

- **Transcript and live session**: Rely on `conversations` and `conversation_turns`. Poll or subscribe to the same DB (or an API that reads these tables). Handle missing or late rows.
- **Safety and redaction**: Read `safety_evaluation` and the stored `child_message` (which may be the redaction placeholder) from `conversation_turns`.
- **Parent guidance**: Not stored in these tables; if needed, the parent app must provide or persist it elsewhere.

## Configuration and connection

- **Database URL**: Datastores use `connection_string` if provided, otherwise `os.environ.get("DATABASE_URL", "sqlite:///kidschat.db")`. So the default is a single SQLite file `kidschat.db` in the current working directory.
- **Singleton access**: `DatastoreFactory.get_datastore("conversation")` (and `"profile"`, `"facts"`, `"user"`, `"story"`, `"interaction_contexts"`) returns a singleton instance per type. The voice backend and any other service (e.g. parent app backend in another repo) should use the same `DATABASE_URL` so all see the same data.
- **Tables**: All tables are created by the datastore layer (`Base.metadata.create_all(self.engine)` in each datastore’s `__init__`). Migrations (Alembic), if used, use the same models from `jubu_chat.chat.datastores.*`.

## Reading data (for parent app or API)

These are the main entry points for a parent app (or backend API) that reads from the same datastore:

- **ConversationDatastore**
  - `get(conversation_id)` → dict with keys `id`, `child_id`, `state`, `start_time`, `end_time`, `last_interaction_time`, `conv_metadata`, `is_archived` (note: the key is `conv_metadata`, not `metadata`).
  - `get_conversation_history(conversation_id, limit=None)` → list of turn dicts, each with `id`, `conversation_id`, `timestamp`, `child_message`, `system_message`, `interaction_type`, `safety_evaluation`, in chronological order.
  - `get_conversations_by_child(child_id, state=None)` → list of conversation dicts (with optional `turn_count` in some code paths).
- **ProfileDatastore**
  - `get_profiles_by_parent(parent_id)` → list of `ChildProfile` domain entities (use `.id`, `.name`, etc.; they are not plain dicts).
  - `get(profile_id)` / `get_child_profile(child_id)` for a single profile.
- **FactsDatastore**
  - `get_active_facts_for_child(child_id)` for facts; `get_facts_by_source_turn(turn_id)` to get facts tied to a turn. Facts are not written from the live conversation flow (see above).

## Visualizing the Datastore Architecture

To help understand the datastore architecture, several diagrams have been created in the repository’s `diagrams/` directory (relative to the project root). The diagrams are available as both PlantUML source files (`.puml`) and as rendered PNG images. If you only have this README, the [Entity Relationship Diagram](#entity-relationship-diagram) text block above can be pasted into [dbdiagram.io](https://dbdiagram.io) or similar tools to generate a visual schema.

### 1. Database Entity-Relationship Diagram

![KidsChat Database Schema](../../../diagrams/KidsChat%20Database%20Schema.png)

This diagram shows the relationships between database tables, including foreign key relationships and cardinality. The diagram visually represents:

- How parent users relate to child profiles
- How child profiles connect to conversations, facts, and stories
- The hierarchy of conversation data with turns and interaction contexts

Source file: `diagrams/database_er_diagram.puml`

### 2. Datastore Class Diagram

![KidsChat Datastore Classes](../../../diagrams/KidsChat%20Datastore%20Classes.png)

This diagram illustrates the object-oriented design of the datastore classes, showing:

- The inheritance hierarchy with `BaseDatastore` as the abstract parent class
- All concrete datastore implementations and their methods
- The `DatastoreFactory` class and its relationships to datastore classes

Source file: `diagrams/datastore_class_diagram.puml`

### 3. Data Access Flow Diagram

![KidsChat Data Access Patterns](../../../diagrams/KidsChat%20Data%20Access%20Patterns.png)

This sequence diagram demonstrates the correct data access patterns in the application, showing:

- How children interact with the physical toy device, which communicates with the server
- How the server processes messages and interacts with the datastores
- How parents use the UI to view conversation logs and set controls
- The complete flow of data: Child → Toy → Server → Datastores → UI → Parent
- How parental controls set through the UI affect future child-toy interactions

Source file: `diagrams/datastore_access_flow.puml`

If you need to modify the diagrams, you can edit the PlantUML source files and regenerate the images using any PlantUML-compatible tool:

```bash
plantuml diagrams/*.puml
```

Online options for rendering PlantUML include:
- [PlantUML Online Server](http://www.plantuml.com/plantuml/uml/)
- [PlantText](https://www.planttext.com/)
- IDE plugins for Visual Studio Code, IntelliJ, etc.

## Design Decisions

### 1. Soft Deletion
All datastores implement soft deletion (marking records as inactive rather than physically deleting them) to:
* Comply with data retention policies
* Allow for data recovery if needed
* Support audit trails

### 2. Data Encryption
Sensitive data is encrypted using the Fernet symmetric encryption algorithm to:
* Protect personally identifiable information (PII)
* Comply with data protection regulations
* Add an additional security layer beyond database access controls

### 3. Connection Pooling
Database connections are managed through a connection pool to:
* Improve performance by reusing connections
* Prevent connection leaks
* Handle concurrent requests efficiently

### 4. Retry Logic
Operations include retry logic for transient database errors to:
* Improve resilience
* Handle temporary network issues
* Recover from database overload situations

### 5. Fact Lifecycle Management
Facts about children have explicit expiration dates to:
* Ensure information freshness
* Comply with data minimization principles
* Allow for automatic cleanup of outdated information

### 6. Hierarchical Configuration
The datastore uses a hierarchical configuration system to:
* Support different environments (development, testing, production)
* Allow for runtime configuration changes
* Provide sensible defaults with override capabilities

### 7. Domain-Specific Types
The datastore uses domain-specific types (like ChildProfile, ConversationTurn) to:
* Improve code readability
* Enforce domain constraints
* Separate domain logic from persistence concerns

## Implementation Notes

1. **SQLAlchemy ORM**: The datastore uses SQLAlchemy for object-relational mapping, providing database independence and query building.
2. **Transaction Management**: All operations use session-based transaction management to ensure data consistency.
3. **Error Handling**: Custom exception types are used for different error scenarios to provide clear error messages.
4. **Indexing Strategy**: Indexes are created on frequently queried fields to improve performance.
5. **Data Validation**: Pydantic models are used for data validation before persistence.

## Future Enhancements

1. **Sharding**: Implement database sharding for horizontal scaling as user base grows.
2. **Caching Layer**: Add Redis caching for frequently accessed data.
3. **Audit Logging**: Implement comprehensive audit logging for all data modifications.
4. **Data Archiving**: Develop a data archiving strategy for long-term storage of inactive data.
5. **Multi-region Replication**: Support multi-region deployment for disaster recovery and reduced latency.

## Toy-Based Interaction Considerations

Based on the architecture where children interact with a physical toy device rather than a UI, the following design considerations should be addressed:

1. **Device Management**:
   - Consider adding a `Devices` table to track toy devices, their association with child profiles, and their connection status
   - Store device-specific preferences and state to ensure personalized toy behavior across sessions

2. **Offline Support**:
   - Implement caching mechanisms in the toy device to handle temporary loss of connectivity
   - Design synchronization protocols for reconciling data when connection is restored

3. **Response Optimization**:
   - Consider toy hardware limitations when storing and transmitting response data
   - Optimize content formats for different toy capabilities (audio, simple display, etc.)

4. **Security Enhancements**:
   - Implement device authentication to ensure only authorized toys can access child data
   - Consider end-to-end encryption for all communication between toy and server

5. **Interaction Logging**:
   - Enhance conversation logging to include device information and connection quality
   - Track physical interaction patterns (when applicable) to improve the experience

6. **Parental Controls**:
   - Add real-time control capabilities to allow parents to monitor and intervene in conversations
   - Implement usage time limits and scheduling through the device management system

7. **Battery and Resource Management**:
   - Design interaction patterns that optimize for battery life of the toy device
   - Implement adaptive content delivery based on device battery levels

These considerations might require extensions to the current datastore schema, particularly adding device-related tables and fields to support the physical toy interaction model.