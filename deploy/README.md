# Deployment Guide

## One-time server setup
1. SSH into your droplet: `ssh root@YOUR_DROPLET_IP`
2. Run: `curl -sSL https://raw.githubusercontent.com/ZakisOK/trading-floor/main/deploy/setup-server.sh | bash`
3. Edit `/opt/trading-floor/.env` — add ANTHROPIC_API_KEY and exchange API keys
4. Set up Cloudflare Tunnel (see below)

## Cloudflare Tunnel setup
1. `cloudflared tunnel login`
2. `cloudflared tunnel create trading-floor`
3. Edit `/opt/trading-floor/deploy/cloudflare-tunnel.yml` — replace YOURDOMAIN.com
4. `cloudflared tunnel route dns trading-floor trading.yourdomain.com`
5. `cloudflared service install`

## Systemd services (auto-start on reboot)
```bash
cp /opt/trading-floor/deploy/trading-floor.service /etc/systemd/system/
cp /opt/trading-floor/deploy/paper-trading.service /etc/systemd/system/
systemctl enable trading-floor paper-trading
systemctl start trading-floor paper-trading
```

## Updates (deploy new code)
```bash
cd /opt/trading-floor && git pull && docker compose restart
```
