# Oracle Cloud + PM2 Deployment Guide

This guide explains how to deploy Balina-Bot on an always-free Oracle Cloud instance using PM2.

## Prerequisites
1. An active Oracle Cloud account (Always Free tier is sufficient: 4 ARM Cores, 24GB RAM).
2. Ubuntu 22.04 LTS provisioned on the VM.
3. SSH access to your instance.

## Server Setup

1. Update packages:
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

2. Install Python 3.10+, pip, and Git:
   ```bash
   sudo apt install python3 python3-pip git -y
   ```

3. Clone the repo and install dependencies:
   ```bash
   git clone <repo-url>
   cd balina_bot
   pip3 install -r requirements.txt
   ```

## PM2 Configuration

PM2 allows the bot to run continuously in the background and auto-restart on crashes.

1. Install Node.js and PM2:
   ```bash
   sudo apt install nodejs npm -y
   sudo npm install pm2 -g
   ```

2. Start the bot:
   ```bash
   pm2 start main.py --interpreter python3 --name "balina-bot"
   ```

3. Enable auto-start on server reboot:
   ```bash
   pm2 startup
   pm2 save
   ```

## Monitoring

- View live logs: `pm2 logs balina-bot`
- View CPU/Memory metrics: `pm2 monit`
- Check FastApi health endpoint: `curl http://localhost:8080/health` (Assuming port 8080)

## Troubleshooting
- **Clock Drift**: Binance API requires strict synchronization. Ensure `chronyd` or `ntpd` is running on your Oracle server.
- **WebSocket Drops**: Check PM2 logs for `Unclosed connector` exceptions. The bot has auto-reconnect logic, but heavy RAM usage might cause OOM kills on smaller instances.
