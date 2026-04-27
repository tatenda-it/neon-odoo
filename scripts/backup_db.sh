#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Neon Odoo nightly Postgres backup
# ─────────────────────────────────────────────────────────────
# Runs pg_dump against the neon_crm database inside the Docker
# container, writes a timestamped .sql.gz file to ./backups/,
# and rotates files older than 30 days.
#
# Designed to be triggered nightly via Windows Task Scheduler
# using Git Bash. Logs go to backups/_backup.log.
# ─────────────────────────────────────────────────────────────

set -euo pipefail

# ── Configuration ──
PROJECT_DIR="/c/Users/USER/neon-odoo"
BACKUP_DIR="$PROJECT_DIR/backups"
DB_NAME="neon_crm"
DB_USER="odoo"
RETENTION_DAYS=30
LOG_FILE="$BACKUP_DIR/_backup.log"

# ── Setup ──
cd "$PROJECT_DIR"
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date '+%Y-%m-%d_%H%M%S')
BACKUP_FILE="$BACKUP_DIR/neon_crm_${TIMESTAMP}.sql.gz"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "──── Backup started ────"

# ── Verify db container is running ──
if ! docker compose ps db | grep -q "Up"; then
    log "ERROR: db container is not running. Aborting."
    exit 1
fi

# ── Run pg_dump ──
log "Dumping $DB_NAME -> $BACKUP_FILE"
if docker compose exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" --no-owner --no-acl | gzip > "$BACKUP_FILE"; then
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    log "Backup complete. Size: $SIZE"
else
    log "ERROR: pg_dump failed"
    rm -f "$BACKUP_FILE"
    exit 2
fi

# ── Verify backup is non-trivial ──
MIN_SIZE_BYTES=10240  # 10 KB minimum (an empty backup is suspicious)
ACTUAL_BYTES=$(stat -c%s "$BACKUP_FILE" 2>/dev/null || stat -f%z "$BACKUP_FILE")
if [ "$ACTUAL_BYTES" -lt "$MIN_SIZE_BYTES" ]; then
    log "WARNING: Backup is suspiciously small ($ACTUAL_BYTES bytes). Keeping but flagging."
fi

# ── Rotate old backups ──
log "Rotating backups older than $RETENTION_DAYS days"
find "$BACKUP_DIR" -name "neon_crm_*.sql.gz" -type f -mtime +$RETENTION_DAYS -print -delete | while read removed; do
    log "  Removed: $(basename "$removed")"
done

# ── Summary ──
TOTAL_BACKUPS=$(find "$BACKUP_DIR" -name "neon_crm_*.sql.gz" -type f | wc -l)
log "Backup chain length: $TOTAL_BACKUPS files"
log "──── Backup completed successfully ────"
