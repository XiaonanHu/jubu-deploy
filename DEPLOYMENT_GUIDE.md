# Jubu Cloud Deployment — Complete Step-by-Step Guide

This guide assumes you have never used GCP, Docker, or cloud deployment before.
Follow every step in order. Do not skip ahead.

---

## Table of Contents

1. [Understanding What We're Building](#1-understanding-what-were-building)
2. [Create a Google Cloud Account](#2-create-a-google-cloud-account)
3. [Install the Google Cloud CLI](#3-install-the-google-cloud-cli)
4. [Create Your Cloud Server (VM)](#4-create-your-cloud-server-vm)
5. [Set Up DNS Subdomains on GoDaddy](#5-set-up-dns-subdomains-on-godaddy)
6. [Connect to Your Server and Install Docker](#6-connect-to-your-server-and-install-docker)
7. [Upload Your Code to the Server](#7-upload-your-code-to-the-server)
8. [Configure Environment Variables](#8-configure-environment-variables)
9. [Start Everything](#9-start-everything)
10. [Set Up SSL Certificates (HTTPS)](#10-set-up-ssl-certificates-https)
11. [Migrate Your Database](#11-migrate-your-database)
12. [Update Your Client Apps](#12-update-your-client-apps)
13. [Verify Everything Works](#13-verify-everything-works)
14. [Everyday Operations](#14-everyday-operations)
15. [Concepts Explained](#15-concepts-explained)

---

## 1. Understanding What We're Building

### What is this?

Right now you start everything with one iTerm script on your MacBook. We're moving
the "server" parts to a computer in the cloud (a Google Cloud VM) so that:

- Your Raspberry Pi can connect to LiveKit from anywhere (not just your home WiFi)
- Your system is always running, even when your MacBook is closed
- You can demo from any location — just bring the Pi and your laptop

### What goes where?

```
YOUR MACBOOK (stays local)
  └── React Native parent app (the UI you show during demos)
      Just change one URL from localhost to https://app.buju.ai

RASPBERRY PI (stays local)
  └── Voice capture app
      Just change LIVEKIT_URL to wss://lk.buju.ai

GOOGLE CLOUD VM (new — what we're setting up)
  └── Everything else:
      ├── LiveKit server (WebRTC voice routing)
      ├── Your backend (livekit_api.py + jubu_thinker.py + bot_manager.py)
      ├── Parent app's API server (app_backend/)
      ├── Redis (your backend already uses this)
      └── PostgreSQL database (replaces your local SQLite kidschat.db)
```

### What is Docker?

Docker is like a shipping container for software. Instead of manually installing
Python, Redis, PostgreSQL, etc. on the cloud server, you define everything in
config files. Then one command (`docker compose up`) starts it all.

Think of it as your iTerm script, but it also installs all the dependencies and
works on any computer.

### What is supervisord?

Your backend has 3 Python processes that need to run simultaneously:
- livekit_api.py (the HTTP API on port 8001)
- jubu_thinker.py (the AI reasoning engine)
- bot_manager.py (spawns voice bots)

Your shell script starts all 3 as background processes. Supervisord does the same
thing inside a Docker container — it runs all 3 processes and restarts them if any
crash. It's a process babysitter.

### What are subdomains?

You own buju.ai. Subdomains are prefixes:
- api.buju.ai → points to your backend API (port 8001)
- app.buju.ai → points to your parent app API (port 8000)
- lk.buju.ai  → points to your LiveKit server

All three point to the same cloud server. Nginx (a traffic router) looks at which
subdomain was used and sends the request to the right service.

### Why do we need HTTPS/SSL?

WebRTC (which LiveKit uses) requires encrypted connections. Browsers and devices
refuse to do WebRTC over unencrypted connections. SSL certificates (from Let's
Encrypt, free) make this work. The domain/subdomain is just a name — it has zero
effect on latency.

---

## 2. Create a Google Cloud Account

### Step 2.1: Go to Google Cloud Console

Open your browser and go to: https://console.cloud.google.com

### Step 2.2: Sign in with your Google account

Use any Google account. Your personal Gmail works fine.

### Step 2.3: Accept terms and start free trial

Google Cloud gives you $300 in free credits for 90 days.
- Click "Agree and Continue"
- You'll need to enter a credit card, but you won't be charged during the trial
- Select your country and accept terms

### Step 2.4: Create a new project

1. Click the project dropdown at the top of the page (it might say "My First Project")
2. Click "NEW PROJECT"
3. Project name: `jubu-production`
4. Click "CREATE"
5. Make sure this project is selected in the dropdown

### Step 2.5: Enable billing

1. Go to: https://console.cloud.google.com/billing
2. Link your project to the billing account that was created with your free trial
3. This is required to create VMs, but the $300 credit covers everything

---

## 3. Install the Google Cloud CLI

The `gcloud` command line tool lets you manage your cloud server from your MacBook's Terminal.

### Step 3.1: Install gcloud

Open Terminal on your Mac and run:

```bash
brew install --cask google-cloud-sdk
```

If you don't have Homebrew, install it first:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### Step 3.2: Initialize gcloud

```bash
gcloud init
```

This will:
1. Open a browser window — sign in with the same Google account
2. Ask which project to use — select `jubu-production`
3. Ask for a default region — choose `us-west1-b` (good for West Coast latency)

### Step 3.3: Verify it works

```bash
gcloud config list
```

You should see your project ID and account email.

---

## 4. Create Your Cloud Server (VM)

### Step 4.1: Enable the Compute Engine API

```bash
gcloud services enable compute.googleapis.com
```

This might take 30 seconds. It enables the ability to create virtual machines.

### Step 4.2: Create the VM

Copy and paste this entire block into Terminal:

```bash
gcloud compute instances create jubu-server \
    --zone=us-west1-b \
    --machine-type=e2-standard-2 \
    --image-family=ubuntu-2404-lts-amd64 \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=50GB \
    --boot-disk-type=pd-ssd \
    --tags=jubu-server
```

This creates a server with:
- 2 CPU cores, 8GB RAM (enough for your workload)
- 50GB SSD storage
- Ubuntu 24.04 (Linux operating system)
- Located in Oregon (us-west1) for low latency

Wait for it to finish. You'll see output with an EXTERNAL_IP — write this down!

### Step 4.3: Get your server's public IP

```bash
gcloud compute instances describe jubu-server \
    --zone=us-west1-b \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
```

This prints your IP address (like `34.82.xxx.xxx`). Write it down.
You'll need it in the next step for DNS.

### Step 4.4: Open firewall ports

Your server needs to accept traffic on specific ports:

```bash
# HTTP and HTTPS (for web traffic)
gcloud compute firewall-rules create jubu-web \
    --allow=tcp:80,tcp:443 \
    --target-tags=jubu-server \
    --description="HTTP and HTTPS"

# LiveKit WebRTC (voice/video data)
gcloud compute firewall-rules create jubu-livekit \
    --allow=tcp:7881,udp:7882-7982 \
    --target-tags=jubu-server \
    --description="LiveKit WebRTC media"
```

---

## 5. Set Up DNS Subdomains on GoDaddy

This tells the internet that api.buju.ai, app.buju.ai, and lk.buju.ai
all point to your GCP server.

### Step 5.1: Log in to GoDaddy

Go to: https://dcc.godaddy.com
Sign in to your account.

### Step 5.2: Go to DNS management

1. Click "Domain Portfolio" (or "My Domains")
2. Find `buju.ai` and click on it
3. Click "DNS" or "Manage DNS"
4. You'll see a table of DNS records

### Step 5.3: Add three A records

Click "Add New Record" three times, once for each:

| Type | Name | Value              | TTL      |
|------|------|--------------------|----------|
| A    | api  | YOUR_VM_IP_ADDRESS | 600      |
| A    | app  | YOUR_VM_IP_ADDRESS | 600      |
| A    | lk   | YOUR_VM_IP_ADDRESS | 600      |

Replace YOUR_VM_IP_ADDRESS with the IP from Step 4.3 (like 34.82.xxx.xxx).

For each one:
1. Click "Add New Record"
2. Type: select "A"
3. Name: type just `api` (not `api.buju.ai` — GoDaddy adds the domain automatically)
4. Value: paste your VM's IP address
5. TTL: 600 seconds (or "10 minutes")
6. Click "Save"

Repeat for `app` and `lk`.

### Step 5.4: Wait for DNS propagation

DNS changes take 5-30 minutes to propagate. You can check if it's working:

```bash
# Run this on your Mac
dig api.buju.ai +short
```

When it returns your VM's IP address, DNS is ready.

---

## 6. Connect to Your Server and Install Docker

### Step 6.1: SSH into your server

```bash
gcloud compute ssh jubu-server --zone=us-west1-b
```

The first time, it will:
- Ask to create an SSH key — press Enter to accept defaults
- Ask for a passphrase — you can leave it empty (just press Enter twice)

You're now inside your cloud server! The prompt changes to something like:
`username@jubu-server:~$`

### Step 6.2: Install Docker

Run these commands one at a time on the server:

```bash
# Update package list
sudo apt-get update

# Install prerequisites
sudo apt-get install -y ca-certificates curl

# Add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Let your user run Docker without sudo
sudo usermod -aG docker $USER
```

### Step 6.3: Apply the group change

Log out and back in so Docker permissions take effect:

```bash
exit
gcloud compute ssh jubu-server --zone=us-west1-b
```

### Step 6.4: Verify Docker works

```bash
docker --version
docker compose version
```

Both should print version numbers. If `docker compose` says "command not found",
run: `sudo apt-get install -y docker-compose-plugin`

### Step 6.5: Go back to your MacBook

```bash
exit
```

You're back on your Mac now.

---

## 7. Upload Your Code to the Server

### Step 7.1: Set up the deploy directory

On your MacBook, create the deploy workspace:

```bash
mkdir -p ~/Dev/jubu-deploy
cd ~/Dev/jubu-deploy
```

### Step 7.2: Extract the deployment package

Take the `jubu-deploy.tar.gz` file I gave you and extract it:

```bash
# If the file is in ~/Downloads:
tar -xzf ~/Downloads/jubu-deploy.tar.gz --strip-components=1 -C ~/Dev/jubu-deploy
```

### Step 7.3: Copy your backend code into the deploy directory

```bash
# Copy the main backend
mkdir -p ~/Dev/jubu-deploy/backend
rsync -av \
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
    --exclude='*.wav' \
    --exclude='voices' \
    --exclude='reference' \
    --exclude='.logs' \
    --exclude='logs' \
    ~/Dev/jubu_backend/ ~/Dev/jubu-deploy/backend/
```

### Step 7.4: Copy the parent app's backend

```bash
mkdir -p ~/Dev/jubu-deploy/parent-api
rsync -av \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='node_modules' \
    --exclude='.DS_Store' \
    ~/Dev/jubu_parent_app/app_backend/ ~/Dev/jubu-deploy/parent-api/
```

### Step 7.5: Copy your Google credentials

```bash
mkdir -p ~/Dev/jubu-deploy/credentials
cp ~/Dev/jubu_backend/credentials/*.json ~/Dev/jubu-deploy/credentials/
```

(Adjust the path if your service account JSON is elsewhere.)

### Step 7.6: Upload everything to the server

```bash
gcloud compute scp --recurse ~/Dev/jubu-deploy jubu-server:~ --zone=us-west1-b --compress
```

This uploads your entire deploy directory to the cloud server.
It might take 2-5 minutes depending on your upload speed (torch is large).

---

## 8. Configure Environment Variables

### Step 8.1: SSH into the server

```bash
gcloud compute ssh jubu-server --zone=us-west1-b
```

### Step 8.2: Create the .env file

```bash
cd ~/jubu-deploy
cp .env.template .env
nano .env
```

This opens a text editor. Fill in your real values:

```
OPENAI_API_KEY=sk-your-real-key-here
GEMINI_API_KEY=your-real-key
OPENAI_ORGANIZATION=org-your-org
ASSEMBLY_API_KEY=your-key
ELEVENLABS_API_KEY=your-key
GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/service-account.json
POSTGRES_PASSWORD=pick-a-strong-password-here-like-K8mP2xQ9
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=devkey-secret-at-least-32-characters!!
PUBLIC_IP=YOUR_VM_IP_ADDRESS
```

Replace YOUR_VM_IP_ADDRESS with the actual IP from Step 4.3.

To save in nano:
1. Press `Ctrl+O` (that's the letter O, not zero)
2. Press `Enter` to confirm
3. Press `Ctrl+X` to exit

### Step 8.3: Go back to your Mac

```bash
exit
```

---

## 9. Start Everything

### Step 9.1: SSH into the server

```bash
gcloud compute ssh jubu-server --zone=us-west1-b
```

### Step 9.2: Start with HTTP-only nginx first

We can't use HTTPS yet because we don't have SSL certificates.
We'll get those in the next section. For now, start with HTTP only:

```bash
cd ~/jubu-deploy

# Use the initial (HTTP-only) nginx config
cp nginx/initial.conf nginx/active.conf

# Build all Docker images (this takes 5-15 minutes the first time)
docker compose build

# Start everything
docker compose up -d
```

The `-d` flag runs everything in the background (detached mode).

### Step 9.3: Check that services are running

```bash
docker compose ps
```

You should see all services as "Up" or "running":
- nginx
- livekit
- backend
- parent-api
- redis
- postgres

If any service shows "Exited" or "Restarting", check its logs:

```bash
docker compose logs backend
docker compose logs parent-api
```

---

## 10. Set Up SSL Certificates (HTTPS)

### Prerequisites

DNS must be working first. Test from the server:

```bash
curl -I http://api.buju.ai
```

If you get a response (even a simple one), DNS is working.
If you get "Could not resolve host", wait longer for DNS propagation (Step 5.4).

### Step 10.1: Stop the temporary nginx

```bash
cd ~/jubu-deploy
docker compose stop nginx
```

### Step 10.2: Get certificates from Let's Encrypt

Run these three commands, one for each subdomain:

```bash
# Certificate for api.buju.ai
docker run --rm -p 80:80 \
    -v jubu-deploy_certbot-certs:/etc/letsencrypt \
    certbot/certbot certonly \
    --standalone \
    -d api.buju.ai \
    --email your-email@buju.ai \
    --agree-tos \
    --no-eff-email \
    --non-interactive

# Certificate for app.buju.ai
docker run --rm -p 80:80 \
    -v jubu-deploy_certbot-certs:/etc/letsencrypt \
    certbot/certbot certonly \
    --standalone \
    -d app.buju.ai \
    --email your-email@buju.ai \
    --agree-tos \
    --no-eff-email \
    --non-interactive

# Certificate for lk.buju.ai
docker run --rm -p 80:80 \
    -v jubu-deploy_certbot-certs:/etc/letsencrypt \
    certbot/certbot certonly \
    --standalone \
    -d lk.buju.ai \
    --email your-email@buju.ai \
    --agree-tos \
    --no-eff-email \
    --non-interactive
```

Replace `your-email@buju.ai` with your real email. Let's Encrypt sends
expiration reminders to this address.

Each command should print "Successfully received certificate".

### Step 10.3: Switch to the full SSL nginx config

```bash
# The default.conf already has the SSL configuration
docker compose up -d
```

### Step 10.4: Test HTTPS

```bash
curl https://api.buju.ai/health
```

If you get a response, HTTPS is working!

---

## 11. Migrate Your Database

Your local SQLite database (kidschat.db) needs to move to PostgreSQL in the cloud.

### Step 11.1: Let your backend create the database schema

The first time your backend starts with PostgreSQL, SQLAlchemy/Alembic should
create all the tables automatically. Check if tables exist:

```bash
docker compose exec postgres psql -U jubu -d jubu -c "\dt"
```

If you see your tables listed, the schema was created.
If the table list is empty, you may need to run Alembic migrations:

```bash
docker compose exec backend alembic upgrade head
```

### Step 11.2: Export data from local SQLite (on your MacBook)

Go back to your Mac (`exit` from the server) and run:

```bash
cd ~/Dev/jubu_backend

python3 << 'EOF'
import sqlite3, json, os

conn = sqlite3.connect("kidschat.db")
cursor = conn.cursor()

cursor.execute("""
    SELECT name FROM sqlite_master
    WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'alembic_%'
""")
tables = [row[0] for row in cursor.fetchall()]

os.makedirs("migration-data", exist_ok=True)

for table in tables:
    cursor.execute(f"SELECT * FROM {table}")
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    
    with open(f"migration-data/{table}.json", "w") as f:
        json.dump({"table": table, "columns": columns,
                   "rows": [list(row) for row in rows]}, f, default=str)
    
    print(f"  {table}: {len(rows)} rows exported")

conn.close()
print("Done! Files in migration-data/")
EOF
```

### Step 11.3: Upload to server

```bash
gcloud compute scp --recurse ~/Dev/jubu_backend/migration-data \
    jubu-server:~/jubu-deploy/ --zone=us-west1-b
```

### Step 11.4: Import into PostgreSQL (on the server)

SSH into the server and run the import. The exact import script depends on your
table structure — you may need to adjust column types. I can help you write a
specific import script once we see what tables you have.

---

## 12. Update Your Client Apps

### Step 12.1: Parent app (React Native on your MacBook)

Open `~/Dev/jubu_parent_app/src/api/config.ts` and change:

```typescript
// BEFORE (local development):
const API_BASE_URL = 'http://localhost:8000';

// AFTER (cloud deployment):
const API_BASE_URL = 'https://app.buju.ai';
```

That's the only change. The React Native app itself still runs on your MacBook.

### Step 12.2: Raspberry Pi (voice app)

In whatever config file your Pi uses for LiveKit, change:

```
# BEFORE:
LIVEKIT_URL=ws://192.168.8.140:7880

# AFTER:
LIVEKIT_URL=wss://lk.buju.ai
```

Note: `ws://` becomes `wss://` (the "s" means encrypted/SSL).

---

## 13. Verify Everything Works

### From your MacBook, test all endpoints:

```bash
# Test the child-facing backend API
curl https://api.buju.ai/health
# Should return a health check response

# Test the parent-facing API
curl https://app.buju.ai/health
# Should return a health check response

# Test LiveKit
curl https://lk.buju.ai
# Should return something (LiveKit's default response)
```

### Test the full flow:

1. Start the parent app on your MacBook: `cd ~/Dev/jubu_parent_app && npm run dev`
2. Connect the Raspberry Pi
3. The Pi should connect to LiveKit via `wss://lk.buju.ai`
4. The parent app should show live updates from `https://app.buju.ai`

---

## 14. Everyday Operations

### Deploying code changes

When you change your backend code, push the update to the cloud:

```bash
# From your MacBook:
cd ~/Dev/jubu-deploy

# Re-sync your backend code
rsync -av \
    --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='.env' --exclude='*.db' --exclude='.DS_Store' \
    --exclude='jubu_datastore' --exclude='tests' \
    ~/Dev/jubu_backend/ ~/Dev/jubu-deploy/backend/

# Upload to server
gcloud compute scp --recurse ~/Dev/jubu-deploy jubu-server:~ --zone=us-west1-b --compress

# Rebuild and restart on server
gcloud compute ssh jubu-server --zone=us-west1-b --command="
    cd ~/jubu-deploy && \
    docker compose build backend && \
    docker compose up -d backend
"
```

### Viewing logs (SSH into server first)

```bash
# All services
docker compose logs -f

# Just the backend
docker compose logs -f backend

# Just the parent API
docker compose logs -f parent-api

# Just LiveKit
docker compose logs -f livekit
```

Press `Ctrl+C` to stop watching logs.

### Restarting a service

```bash
docker compose restart backend
docker compose restart parent-api
docker compose restart livekit
```

### Restarting everything

```bash
docker compose down    # stop everything
docker compose up -d   # start everything
```

### Backing up the database

```bash
docker compose exec postgres pg_dump -U jubu jubu > backup_$(date +%Y%m%d).sql
```

### Checking how much disk space you're using

```bash
df -h /
docker system df
```

### Stopping the server to save money (when not in use)

From your MacBook:
```bash
# Stop the VM (you stop paying for compute, but disk still costs ~$8/month)
gcloud compute instances stop jubu-server --zone=us-west1-b

# Start it again when you need it
gcloud compute instances start jubu-server --zone=us-west1-b
```

Note: When you restart the VM, the public IP might change. If it does,
update your GoDaddy DNS records.

To keep a fixed IP (recommended):
```bash
# One-time: reserve a static IP
gcloud compute addresses create jubu-ip --region=us-west1
gcloud compute instances delete-access-config jubu-server --zone=us-west1-b --access-config-name="External NAT"
gcloud compute instances add-access-config jubu-server --zone=us-west1-b --address=$(gcloud compute addresses describe jubu-ip --region=us-west1 --format='get(address)')
```

---

## 15. Concepts Explained

### Docker

Docker packages your application and all its dependencies into a "container" —
a lightweight, portable unit that runs the same way everywhere. Instead of
installing Python 3.12, Redis, PostgreSQL, etc. directly on the server, Docker
handles it all. Each service runs in isolation.

### Docker Compose

Docker Compose is a tool that runs multiple Docker containers together. Our
`docker-compose.yml` defines 7 services. The command `docker compose up -d`
starts all of them with the right networking, volumes, and environment variables.

### Supervisord

Supervisord is a process manager. Inside the backend Docker container, we need
to run 3 Python scripts simultaneously (API, Thinker, Bot Manager). Supervisord
starts all three, monitors them, and automatically restarts any that crash.
It's doing the same job as your iTerm panes, but inside a container.

### Nginx

Nginx is a web server that sits in front of your services. It handles:
- TLS/SSL (encrypting traffic with HTTPS)
- Routing: looks at the subdomain and forwards to the right service
- Security headers

### Let's Encrypt / Certbot

Let's Encrypt provides free SSL certificates (the files that enable HTTPS).
Certbot is the tool that requests and renews these certificates automatically.
Certificates expire every 90 days, but our certbot container auto-renews them.

### PostgreSQL vs SQLite

SQLite stores your entire database in a single file (kidschat.db). This is fine
for local development but breaks in containers (data is lost when the container
restarts) and can't handle multiple processes writing at the same time.

PostgreSQL is a real database server that runs as its own process, handles
concurrent access safely, and stores data in a Docker volume that persists
across container restarts.

### Volumes

Docker volumes are persistent storage. Without a volume, data inside a container
is lost when the container restarts. We use volumes for PostgreSQL data, Redis
data, and SSL certificates so they survive restarts.

### Firewall Rules

By default, Google Cloud blocks all incoming traffic to your VM. Firewall rules
open specific ports:
- Port 80: HTTP (for Let's Encrypt certificate verification)
- Port 443: HTTPS (for all your services)
- Port 7881: LiveKit TCP signaling
- Ports 7882-7982: LiveKit UDP media (actual voice data)

---

## Cost Summary

| Item                    | Monthly Cost |
|-------------------------|-------------|
| e2-standard-2 VM        | ~$49        |
| 50GB SSD disk            | ~$8.50      |
| Network egress           | ~$5-10      |
| Static IP (if reserved)  | ~$0 (free while attached to running VM) |
| SSL certificates         | Free        |
| **Total**                | **~$60-70/month** |

**Saving money:** Stop the VM when not in use. You only pay ~$8/month for the
disk while the VM is stopped. When preparing for a demo, start the VM 5 minutes
beforehand.

**Free credits:** Apply for Google Cloud for Startups at
https://cloud.google.com/startup — you can get $100K+ in credits.

---

## Troubleshooting

### "Connection refused" when testing endpoints

Services might not be fully started. Wait 30 seconds and try again.
Check logs: `docker compose logs backend`

### Docker build fails

Check the error message. Common causes:
- Missing requirements in requirements-deploy.txt
- GitHub token needed for private repo (jubu_datastore)
- Out of disk space: `df -h /`

### SSL certificate fails

- DNS must be propagated first: `dig api.buju.ai +short` should show your IP
- Port 80 must be open: check firewall rules
- Wait and retry — Let's Encrypt has rate limits

### Backend container keeps restarting

Check logs: `docker compose logs backend`
Common causes:
- Missing environment variable in .env
- PostgreSQL not ready yet (should resolve after a few retries)
- Python import error (missing dependency in requirements-deploy.txt)

### Can't SSH into the server

```bash
# Check if the VM is running
gcloud compute instances list

# If it's TERMINATED, start it
gcloud compute instances start jubu-server --zone=us-west1-b
```
