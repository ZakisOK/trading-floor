#!/bin/bash
# Run this on the DigitalOcean droplet to set up the server
set -e

echo "=== Setting up The Trading Floor server ==="

# Install Docker
apt-get update -q
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update -q
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin git

# Install Node.js 20
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

# Install Python 3.11
apt-get install -y python3.11 python3.11-venv python3-pip

# Clone repo
git clone https://github.com/ZakisOK/trading-floor.git /opt/trading-floor
cd /opt/trading-floor

# Copy env file
cp .env.example .env
echo "=== Edit /opt/trading-floor/.env and add your ANTHROPIC_API_KEY ==="

# Build frontend
cd frontend && npm install && npm run build && cd ..

# Set up Python venv
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]" --quiet

# Start services
docker compose up -d

# Wait for postgres
sleep 10

# Run migrations
source .venv/bin/activate && alembic upgrade head

# Install cloudflared
curl -L --output /usr/local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x /usr/local/bin/cloudflared

echo "=== Setup complete. Now configure Cloudflare Tunnel ==="
echo "Run: cloudflared tunnel login"
