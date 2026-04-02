#!/bin/bash
# ==========================================================
# Deploy — build and push to GCP VM
# Run from your MacBook in the jubu-deploy/ directory
# ==========================================================
set -e

# ---- Configuration (edit these) ----
INSTANCE_NAME="jubu-server"
ZONE="us-west1-b"
BACKEND_DIR="$HOME/Dev/jubu_backend"
PARENT_APP_DIR="$HOME/Dev/jubu_parent_app"
DEPLOY_DIR="$(cd "$(dirname "$0")/.." && pwd)"  # jubu-deploy/

echo ""
echo "=========================================="
echo "  Jubu — Deploying to Cloud"
echo "=========================================="
echo ""

# ── Step 1: Sync backend code ──
echo "[1/4] Syncing backend code..."
mkdir -p "$DEPLOY_DIR/backend"
rsync -av --delete \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='.mypy_cache' \
    --exclude='.pytest_cache' \
    --exclude='*.db' \
    --exclude='.logs' \
    --exclude='.*.log' \
    --exclude='temp_audio' \
    --exclude='.DS_Store' \
    --exclude='jubu_datastore' \
    --exclude='diagrams' \
    --exclude='docs' \
    --exclude='tests' \
    --exclude='evaluation' \
    --exclude='*.egg-info' \
    "$BACKEND_DIR/" "$DEPLOY_DIR/backend/"

# ── Step 2: Sync parent API code ──
echo "[2/4] Syncing parent API code..."
mkdir -p "$DEPLOY_DIR/parent-api"
rsync -av --delete \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='node_modules' \
    --exclude='.DS_Store' \
    "$PARENT_APP_DIR/app_backend/" "$DEPLOY_DIR/parent-api/"

# ── Step 3: Upload to VM ──
echo "[3/4] Uploading to GCP VM..."
gcloud compute scp --recurse "$DEPLOY_DIR" \
    "$INSTANCE_NAME":~/jubu-deploy \
    --zone="$ZONE" \
    --compress

# ── Step 4: Build and restart on VM ──
echo "[4/4] Building and restarting services..."
gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" --command="
    cd ~/jubu-deploy
    docker compose build --build-arg GITHUB_TOKEN=\$(grep GITHUB_TOKEN .env | cut -d= -f2)
    docker compose up -d
    echo ''
    echo 'Services:'
    docker compose ps
"

echo ""
echo "=========================================="
echo "  Deploy Complete!"
echo "=========================================="
echo ""

# Health checks
echo "Checking services..."
sleep 8

echo -n "  api.buju.ai:  "
curl -sf https://api.buju.ai/health && echo "✅" || echo "❌ (may need a moment)"

echo -n "  app.buju.ai:  "
curl -sf https://app.buju.ai/health && echo "✅" || echo "❌ (may need a moment)"

echo -n "  lk.buju.ai:   "
curl -sf https://lk.buju.ai && echo "✅" || echo "❌ (may need a moment)"
echo ""
