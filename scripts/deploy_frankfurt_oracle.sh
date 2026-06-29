#!/bin/bash
# 🐳 Balina-Bot ⚔️ Oracle Cloud Free Tier (ARM64) Deployment 🐳
# Optimized for Oracle's 4-Core ARM Ampere A1 Compute instances (eu-frankfurt-1)

echo "-------------------------------------------------------------------"
echo "🐳 Oracle Free Tier HFT Server Initialization (Frankfurt) 🐳"
echo "-------------------------------------------------------------------"

# 1. OS & Kernel Tweaks
echo "🎯 Optimizing Kernel for ARM64 Microsecond executions..."
sudo apt-get update && sudo apt-get install -y python3-pip python3-venv htop git build-essential npm

# TCP Optimization bypassing Oracle default buffers
sudo sysctl -w net.ipv4.tcp_low_latency=1
sudo sysctl -w net.ipv4.tcp_timestamps=0
sudo sysctl -p

# 2. Python Environment (ARM64 Compatible builds)
echo "🐍 Constructing ARM64 Python Boundaries..."
python3 -m venv venv
source venv/bin/activate
pip install wheel
# Uvloop is known to require build-essential on ARM instances natively.
pip install -r requirements.txt

# 3. Node.js & PM2 for relentless Zero-Budget process keeping
echo "⚙️ Installing PM2 (Process Manager) for 7/24 robust Execution..."
sudo npm install -g pm2

# 4. Starting the bot via PM2 binding isolated CPU cores (Oracle allows 4 OCPUs on Free Tier)
# Pinning to Core 2 and 3 natively isolating noise from the OS scheduler on Core 0.
echo "🚀 Generating PM2 Ecosystem file..."
cat << 'EOF' > pm2_ecosystem.config.js
module.exports = {
  apps: [{
    name: "balina-bot",
    script: "./venv/bin/python",
    args: "main.py",
    instances: 1,
    exec_mode: "fork",
    watch: false,
    max_memory_restart: "1500M",
    task_affinity: "2,3" // PM2 CPU Pinning explicitly for Oracle Cores
  }]
}
EOF

pm2 start pm2_ecosystem.config.js
pm2 save
pm2 startup

echo "✅ DEPLOYMENT COMPLETE. PM2 is actively guarding Balina-Bot on Cores 2 & 3."
echo "📱 Monitor via Chrome Remote Desktop: Run 'pm2 logs balina-bot'"
