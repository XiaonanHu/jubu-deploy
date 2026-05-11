#!/bin/bash
# Free up disk space before/after a Docker build.
# Removes build cache and unused images. Leaves running containers
# and named volumes (e.g. postgres-data) untouched.
set -e

echo "=== Disk usage BEFORE ==="
df -h /
echo
docker system df
echo

echo "=== Pruning build cache ==="
docker builder prune -af

echo
echo "=== Pruning dangling/unused images ==="
# -a removes images not referenced by any container. Running containers
# (postgres, redis, nginx, certbot, livekit, backend, parent-api) keep
# their images safe.
docker image prune -af

echo
echo "=== Pruning stopped containers and unused networks ==="
docker container prune -f
docker network prune -f

echo
echo "=== Disk usage AFTER ==="
df -h /
echo
docker system df
