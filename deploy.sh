#!/bin/bash
set -e
cd ~/jubu-deploy
source ~/.github_token
git pull
echo "Building..."
docker compose build --no-cache --build-arg GITHUB_TOKEN=$GITHUB_TOKEN
echo "Starting..."
docker compose up -d
docker compose restart nginx
echo ""
docker compose ps
