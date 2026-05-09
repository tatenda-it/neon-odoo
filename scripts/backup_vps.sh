#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=/opt/neon-odoo/backups
mkdir -p $BACKUP_DIR

echo "Starting backup $DATE..."

# Dump PostgreSQL
docker exec neon-odoo-db pg_dump -U odoo neon_crm | gzip > $BACKUP_DIR/neon_crm_$DATE.sql.gz

# Keep only last 30 backups
ls -t $BACKUP_DIR/*.sql.gz | tail -n +31 | xargs rm -f 2>/dev/null

echo "Backup complete: neon_crm_$DATE.sql.gz"
ls -lh $BACKUP_DIR/
