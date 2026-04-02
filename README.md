# Jubu Cloud Deployment

## Architecture

```
                                    ┌──────────── GCP VM ────────────────────┐
                                    │                                        │
┌──────────────┐  wss://lk.buju.ai  │   ┌─────────┐     ┌──────────────┐   │
│ Raspberry Pi │ ◄─────────────────►│   │ LiveKit  │     │   nginx      │   │
│ (voice I/O)  │                    │   │ Server   │◄────│   (TLS)      │   │
└──────────────┘                    │   └─────────┘     └──────┬───────┘   │
                                    │                      443 │ 80        │
┌──────────────┐ https://app.buju.ai│   ┌──────────────┐      │           │
│   MacBook    │ ◄─────────────────►│   │ Parent API   │◄─────┤           │
│  (React      │                    │   │ (port 8000)  │      │           │
│   Native)    │                    │   └──────┬───────┘      │           │
└──────────────┘                    │          │               │           │
                                    │   ┌──────┴───────┐      │           │
                                    │   │  PostgreSQL   │      │           │
                                    │   │  (shared DB)  │      │           │
                                    │   └──────┬───────┘      │           │
                                    │          │               │           │
                                    │   ┌──────┴───────┐      │           │
                                    │   │   Backend     │◄─────┘           │
                                    │   │ (port 8001)   │                  │
                                    │   │ ├─ API        │     ┌────────┐  │
                                    │   │ ├─ Thinker    │◄────│ Redis  │  │
                                    │   │ └─ BotManager │     └────────┘  │
                                    │   └──────────────┘                  │
                                    └─────────────────────────────────────┘

Subdomains:
  api.buju.ai  → Backend (child-facing LiveKit API, port 8001)
  app.buju.ai  → Parent API (parent-facing REST, port 8000)
  lk.buju.ai   → LiveKit signaling (WebSocket, port 7880)
```

## Step-by-Step Deployment

### Phase 1: GCP VM

```bash
# From your MacBook:
bash scripts/gcp-setup.sh
```

This creates an `e2-standard-2` VM (2 vCPU, 8GB RAM, 50GB SSD) with Docker.

### Phase 2: DNS Records

In your domain registrar (wherever buju.ai is managed), add three A records:

| Type | Name  | Value              |
|------|-------|--------------------|
| A    | api   | `<your VM's IP>`   |
| A    | app   | `<your VM's IP>`   |
| A    | lk    | `<your VM's IP>`   |

Wait 5-10 minutes for DNS propagation. Verify: `dig api.buju.ai`

### Phase 3: Configure

```bash
# In the jubu-deploy/ directory:
cp .env.template .env
# Edit .env — fill in all your API keys, set POSTGRES_PASSWORD, set PUBLIC_IP

# Copy Google service account credentials
mkdir -p credentials
cp ~/path/to/your-service-account.json credentials/service-account.json
```

### Phase 4: First Deploy

```bash
# Push everything to the VM:
bash scripts/deploy.sh

# SSH into the VM:
gcloud compute ssh jubu-server --zone=us-west1-b

# On the VM — get SSL certificates:
cd ~/jubu-deploy
bash scripts/setup-ssl.sh
```

### Phase 5: Migrate Database

```bash
# On your MacBook — export SQLite data:
bash scripts/migrate-sqlite-to-postgres.sh

# Follow the printed instructions to import on the VM
```

### Phase 6: Update Client Apps

**Parent app** (`src/api/config.ts`):
```typescript
// Change from:
const API_BASE_URL = 'http://localhost:8000';
// To:
const API_BASE_URL = 'https://app.buju.ai';
```

**Raspberry Pi** (voice app config):
```
LIVEKIT_URL=wss://lk.buju.ai
```

---

## Everyday Operations

### Deploy code changes
```bash
bash scripts/deploy.sh    # one command from MacBook
```

### View logs
```bash
# SSH into VM first, then:
docker compose logs -f              # all services
docker compose logs -f backend      # just backend
docker compose logs -f parent-api   # just parent API
docker compose logs -f livekit      # just LiveKit
```

### Restart a service
```bash
docker compose restart backend
docker compose restart parent-api
```

### Database backup
```bash
docker compose exec postgres pg_dump -U jubu jubu > backup_$(date +%Y%m%d).sql
```

### SSH into backend container (debugging)
```bash
docker compose exec backend bash
```

---

## File Structure

```
jubu-deploy/
├── docker-compose.yml              # Orchestrates all 7 services
├── .env.template                   # Environment variables template
├── .dockerignore
├── requirements-deploy.txt         # Backend Python deps
├── requirements-parent-api.txt     # Parent API Python deps
│
├── docker/
│   ├── Dockerfile.backend          # Backend image (API + Thinker + BotMgr)
│   ├── Dockerfile.parent-api       # Parent API image
│   ├── supervisord-backend.conf    # Process manager for backend
│   └── livekit-production.yaml     # LiveKit production config
│
├── nginx/
│   ├── default.conf                # Full SSL config (3 subdomains)
│   └── initial.conf                # HTTP-only (for SSL bootstrapping)
│
├── credentials/                    # Google service account (NOT in git)
│   └── service-account.json
│
├── scripts/
│   ├── gcp-setup.sh                # Create GCP VM
│   ├── setup-ssl.sh                # Get SSL certificates
│   ├── deploy.sh                   # Push code + restart
│   └── migrate-sqlite-to-postgres.sh
│
├── backend/                        # (created by deploy.sh — your jubu_backend code)
├── parent-api/                     # (created by deploy.sh — your app_backend code)
└── README.md
```

## Cost Estimate

| Resource               | Monthly Cost |
|------------------------|-------------|
| e2-standard-2 VM       | ~$49        |
| 50GB SSD               | ~$8.50      |
| Network egress          | ~$5-10      |
| **Total**              | **~$60-70** |

Apply for [Google Cloud for Startups](https://cloud.google.com/startup) to get $100K+ in credits.
# jubu-deploy
