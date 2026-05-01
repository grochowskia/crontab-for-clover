#!/bin/bash
# Setup script for AOS restart automation
# This script sets up cron jobs to run AOS restart at midnight PST/PDT

SCRIPT_PATH="/root/aos_restart.py"
LOG_PATH="/var/log/aos_restart_cron.log"
PASSWORD="NewAdminPassword123!"  # Change this to your desired password

echo "Setting up AOS restart automation..."

# Check if the AOS restart script exists
if [ ! -f "$SCRIPT_PATH" ]; then
    echo "ERROR: AOS restart script not found at $SCRIPT_PATH"
    echo "Please copy your aos_restart.py script to $SCRIPT_PATH first"
    exit 1
fi

# Make sure the script is executable
chmod +x "$SCRIPT_PATH"

# Create log directory if it doesn't exist
mkdir -p "$(dirname "$LOG_PATH")"

# Backup current crontab
echo "Backing up current crontab..."
crontab -l > /tmp/crontab_backup_$(date +%Y%m%d_%H%M%S) 2>/dev/null || echo "No existing crontab found"

# Create new cron job entry
echo "Creating cron job for AOS restart..."

# Method 1: Two separate cron jobs for PST and PDT
cat > /tmp/aos_cron_jobs << 'EOF'
# AOS Service Restart - Midnight PST (UTC-8) = 8:00 AM UTC
# Runs during Pacific Standard Time (roughly Nov-Mar)
0 8 * 11-12,1-3 * /usr/bin/python3 /root/aos_restart.py -y --password "REPLACE_PASSWORD" >> /var/log/aos_restart_cron.log 2>&1

# AOS Service Restart - Midnight PDT (UTC-7) = 7:00 AM UTC  
# Runs during Pacific Daylight Time (roughly Mar-Nov)
0 7 * 3-10 * /usr/bin/python3 /root/aos_restart.py -y --password "REPLACE_PASSWORD" >> /var/log/aos_restart_cron.log 2>&1
EOF

# Replace password placeholder
sed -i "s/REPLACE_PASSWORD/$PASSWORD/g" /tmp/aos_cron_jobs

# Add timezone-aware comment
cat > /tmp/aos_cron_final << EOF
# AOS Service Restart Automation
# Runs at midnight Pacific Time (PST/PDT)
# Server timezone: $(timedatectl show --property=Timezone --value 2>/dev/null || echo "UTC")
# 
$(cat /tmp/aos_cron_jobs)

EOF

# Install the new cron jobs
echo "Installing cron jobs..."
(crontab -l 2>/dev/null; echo ""; cat /tmp/aos_cron_final) | crontab -

# Clean up temporary files
rm -f /tmp/aos_cron_jobs /tmp/aos_cron_final

echo "✅ Cron jobs installed successfully!"
echo ""
echo "Current cron jobs:"
crontab -l | grep -A 5 -B 2 "AOS Service"
echo ""
echo "Log file location: $LOG_PATH"
echo "To monitor the log: tail -f $LOG_PATH"
echo ""
echo "To remove these cron jobs later:"
echo "  crontab -e  # Then delete the AOS-related lines"