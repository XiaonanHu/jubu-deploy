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

### Switch LLM model or provider (zero downtime)
Model choice lives in one file: `config-overrides/model_routing.yaml`
(bind-mounted into backend and parent-api). Each role maps to a failover
chain of model config names from jubu_backend `jubu_chat/configs/models/`.

```bash
# On the server — edit the chain, no rebuild, no restart:
vim ~/jubu-deploy/config-overrides/model_routing.yaml
# New conversations pick up the change immediately; active ones finish
# on the old chain.
```

Failover is automatic: if the primary provider errors out, the next model
in the chain serves the request, and a per-provider circuit breaker skips
a downed provider for 30s at a time. Watch for `FAILOVER` /
`Circuit breaker` WARNING lines in `docker compose logs backend`.

Env vars `MODEL_CHAIN_<ROLE>` / `MODEL_CHAIN_DEFAULT` in `.env` override
the file (comma-separated, e.g. `MODEL_CHAIN_CONVERSATION=gemini-3.5-flash,claude-haiku-4-5`)
but require `docker compose up -d` to take effect. OpenRouter needs
`OPENROUTER_API_KEY` in `.env`.

### Stop VM (save money)
```bash
gcloud compute instances stop jubu-server --zone=us-west1-b
```

### Start VM
```bash
gcloud compute instances start jubu-server --zone=us-west1-b
# Everything auto-restarts — no manual steps needed
```
