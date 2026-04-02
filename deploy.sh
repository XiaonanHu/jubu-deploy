#!/bin/bash
set -e
cd ~/jubu-deploy
source ~/.github_token
git pull
echo "Building..."
docker compose build --build-arg GITHUB_TOKEN=$GITHUB_TOKEN --build-arg CACHE_BUST=$(date +%s)
echo "Starting..."
docker compose up -d
docker compose restart nginx
echo ""
docker compose ps
