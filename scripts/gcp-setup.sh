#!/bin/bash
# ==========================================================
# GCP VM Setup — run from your MacBook
# Creates VM, installs Docker, opens firewall ports
# ==========================================================
set -e

# ---- Configuration (edit these) ----
PROJECT_ID="jubu-production"        # Your GCP project ID
ZONE="us-west1-b"                   # Low latency to West Coast
INSTANCE_NAME="jubu-server"
MACHINE_TYPE="e2-standard-2"        # 2 vCPU, 8GB RAM

echo ""
echo "=========================================="
echo "  Jubu — GCP VM Setup"
echo "=========================================="
echo ""

# Step 1: Set project
echo "[1/5] Setting GCP project..."
gcloud config set project "$PROJECT_ID"

# Step 2: Enable APIs
echo "[2/5] Enabling Compute Engine API..."
gcloud services enable compute.googleapis.com

# Step 3: Create VM
echo "[3/5] Creating VM ($MACHINE_TYPE in $ZONE)..."
gcloud compute instances create "$INSTANCE_NAME" \
    --zone="$ZONE" \
    --machine-type="$MACHINE_TYPE" \
    --image-family=ubuntu-2404-lts-amd64 \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=50GB \
    --boot-disk-type=pd-ssd \
    --tags=jubu-server \
    --metadata=startup-script='#!/bin/bash
        # Install Docker
        apt-get update
        apt-get install -y ca-certificates curl
        install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
        chmod a+r /etc/apt/keyrings/docker.asc
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
        apt-get update
        apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
        systemctl enable docker
        systemctl start docker
        # Allow non-root docker usage
        usermod -aG docker $(ls /home/ | head -1)
    '

# Step 4: Firewall rules
echo "[4/5] Creating firewall rules..."

gcloud compute firewall-rules create jubu-web \
    --allow=tcp:80,tcp:443 \
    --target-tags=jubu-server \
    --description="HTTP/HTTPS for nginx" \
    2>/dev/null || echo "  jubu-web rule already exists"

gcloud compute firewall-rules create jubu-livekit \
    --allow=tcp:7881,udp:7882-7982 \
    --target-tags=jubu-server \
    --description="LiveKit WebRTC media" \
    2>/dev/null || echo "  jubu-livekit rule already exists"

# Step 5: Get external IP
echo "[5/5] Getting VM external IP..."
sleep 5  # Wait for VM to get an IP
EXTERNAL_IP=$(gcloud compute instances describe "$INSTANCE_NAME" \
    --zone="$ZONE" \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)')

echo ""
echo "=========================================="
echo "  VM Ready!"
echo "=========================================="
echo ""
echo "  External IP:  $EXTERNAL_IP"
echo ""
echo "  ┌─────────────────────────────────────────────┐"
echo "  │  DNS Records to Add (in your domain panel):  │"
echo "  │                                               │"
echo "  │  A   api.buju.ai  →  $EXTERNAL_IP       │"
echo "  │  A   app.buju.ai  →  $EXTERNAL_IP       │"
echo "  │  A   lk.buju.ai   →  $EXTERNAL_IP       │"
echo "  └─────────────────────────────────────────────┘"
echo ""
echo "  Next steps:"
echo "    1. Add the DNS records above"
echo "    2. Wait ~5 min for Docker to install on VM"
echo "    3. SSH in:  gcloud compute ssh $INSTANCE_NAME --zone=$ZONE"
echo "    4. Verify:  docker --version"
echo ""
echo "  Then deploy:"
echo "    bash scripts/deploy.sh"
