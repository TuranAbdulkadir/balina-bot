#!/bin/bash
# 🐳 Balina-Bot ⚔️ HFT Deployment Script (AWS eu-central-1 Frankfurt) 🐳
# Description: Automates Kernel optimizations configuring OS components specifically allowing microsecond executions maximizing latency parity inside Binance's AWS instance zone.

echo "-------------------------------------------------------------------"
echo "🐳 Balina-Bot HFT Server Initialization Protocol (Frankfurt AWS) 🐳"
echo "-------------------------------------------------------------------"

# 1. Updating OS and optimizing kernel parameters for microsecond networking bounds
echo "Running system network optimizations mapping local TCP pipelines..."
sudo apt-get update && sudo apt-get install -y python3-pip python3-venv htop numactl git

# TCP Optimization bypassing latency algorithms (Nagle's algo and buffer bloat optimization bypasses)
sudo sysctl -w net.ipv4.tcp_low_latency=1
sudo sysctl -w net.ipv4.tcp_timestamps=0
sudo sysctl -p

# 2. Virtual Env and Requirements Loading
echo "Constructing virtual container mapping Python boundaries..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Applying Ubuntu CPU Core Pinning & NUMA Node configuration isolating OS noise 
echo "Generating Daemon systemd file establishing isolated Core Pinning architecture..."

cat << 'EOF' > /etc/systemd/system/balinabot.service
[Unit]
Description=Balina-Bot HFT Engine
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/balina-bot
# Pinned strictly to CPU Core 2 and 3 for maximizing L3 Cache hits avoiding unpredictable context switching natively handled by NUMA policies.
ExecStart=/usr/bin/numactl --physcpubind=2,3 --localalloc /root/balina-bot/venv/bin/python main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable balinabot
echo "Deployment system initialization completed successfully."
echo "TARGET: /etc/systemd/system/balinabot.service"
echo "⚠️ WARNING: Double check your native .env variable allocations before invoking: systemctl start balinabot"
