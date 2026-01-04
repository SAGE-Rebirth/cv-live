#!/bin/bash
# setup_cron.sh

# Define the cron job command (Daily restart at 3 AM)
CRON_JOB="0 3 * * * sudo systemctl restart cv-live"

# Check if the job already exists
(crontab -l 2>/dev/null | grep -F "$CRON_JOB") && echo "Cron job already exists." && exit 0

# Add the job
(crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
echo "Cron job added: Daily restart at 3 AM."
