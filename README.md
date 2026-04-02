# Jubu Cloud Deployment

## Architecture

```
┌──────────────┐  wss://lk.buju.ai   ┌──── GCP VM ─────────────────────┐
│ Raspberry Pi │ ◄───────────────────►│  nginx (TLS) → LiveKit          │
└──────────────┘                      │  nginx (TLS) → Backend (:8001)  │
┌──────────────┐  https://app.buju.ai │  nginx (TLS) → Parent API (:8k)│
│   MacBook    │ ◄───────────────────►│  PostgreSQL  │  Redis           │
│ (React Native)│                     └─────────────────────────────────┘
└──────────────┘
```

## Deploy Workflow

Everything is Git-based. No file copying, no rsync.

```bash
# On your Mac: push code changes
cd ~/Dev/jubu_backend && git push
cd ~/Dev/jubu_parent_app && git push

# On the server: pull and rebuild
gcloud compute ssh jubu-server --zone=us-west1-b
cd ~/jubu-deploy
git pull
docker compose build --build-arg GITHUB_TOKEN=$GITHUB_TOKEN
docker compose up -d
```

## Repo Structure (what gets committed)

```
jubu-deploy/
├── docker-compose.yml
├── .env.template           # Template only — .env is gitignored
├── .gitignore
├── requirements-deploy.txt
├── requirements-parent-api.txt
├── docker/
│   ├── Dockerfile.backend          # Clones jubu_backend from GitHub
│   ├── Dockerfile.parent-api       # Clones jubu_parent_app from GitHub
│   ├── supervisord-backend.conf
│   └── livekit-production.yaml
├── nginx/
│   ├── default.conf                # SSL config
│   └── initial.conf                # HTTP-only (first-time setup)
└── scripts/
    ├── gcp-setup.sh
    ├── setup-ssl.sh
    ├── deploy.sh
    └── migrate-sqlite-to-postgres.sh
```

NOT committed (in .gitignore):
- `.env` (secrets)
- `credentials/` (Google service account)
- `backend/` (old rsync artifacts)
- `parent-api/` (old rsync artifacts)

## First-Time Setup

See DEPLOYMENT_GUIDE.md for the full walkthrough.

## Everyday Operations

### Deploy code changes
```bash
gcloud compute ssh jubu-server --zone=us-west1-b
cd ~/jubu-deploy && git pull
docker compose build --build-arg GITHUB_TOKEN=$GITHUB_TOKEN
docker compose up -d
```

### View logs
```bash
docker compose logs -f backend
docker compose logs -f parent-api
docker compose logs -f livekit
```

### Stop VM (save money)
```bash
gcloud compute instances stop jubu-server --zone=us-west1-b
```

### Start VM
```bash
gcloud compute instances start jubu-server --zone=us-west1-b
# Everything auto-restarts — no manual steps needed
```
