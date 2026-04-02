#!/bin/bash
# ==========================================================
# First-time SSL setup via Let's Encrypt
# Run ONCE on the VM after DNS is pointing to this server
# ==========================================================
set -e

EMAIL="your-email@buju.ai"  # ← CHANGE THIS
DOMAINS=("api.buju.ai" "app.buju.ai" "lk.buju.ai")

echo ""
echo "=========================================="
echo "  SSL Certificate Setup"
echo "=========================================="
echo ""

# Step 1: Use HTTP-only nginx for ACME challenge
echo "[1/3] Starting nginx in HTTP-only mode..."
cp nginx/initial.conf nginx/active.conf

# Temporarily swap in initial config
docker compose down nginx 2>/dev/null || true
docker run -d --name certbot-nginx \
    -p 80:80 \
    -v "$(pwd)/nginx/initial.conf:/etc/nginx/conf.d/default.conf:ro" \
    -v jubu-deploy_certbot-webroot:/var/www/certbot \
    nginx:alpine

sleep 2

# Step 2: Request certificates
echo "[2/3] Requesting certificates..."
for domain in "${DOMAINS[@]}"; do
    echo "  → $domain"
    docker run --rm \
        -v jubu-deploy_certbot-webroot:/var/www/certbot \
        -v jubu-deploy_certbot-certs:/etc/letsencrypt \
        certbot/certbot certonly \
            --webroot \
            -w /var/www/certbot \
            -d "$domain" \
            --email "$EMAIL" \
            --agree-tos \
            --no-eff-email \
            --non-interactive
done

# Cleanup temp nginx
docker stop certbot-nginx && docker rm certbot-nginx

# Step 3: Start everything with SSL
echo "[3/3] Starting all services with SSL..."
docker compose up -d

echo ""
echo "=========================================="
echo "  SSL Setup Complete!"
echo "=========================================="
echo ""
echo "  Test endpoints:"
echo "    curl https://api.buju.ai/health"
echo "    curl https://app.buju.ai/health"
echo "    curl https://lk.buju.ai"
echo ""
echo "  Certificates auto-renew via the certbot container."
