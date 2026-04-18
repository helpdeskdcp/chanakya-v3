"""
Chanakya v3 — Auto DB Backup
Daily backup with retention policy
"""
import os, shutil, logging, sqlite3, threading, time
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

BACKUP_DIR = "data/backups"
KEEP_DAYS  = 30  # Retain last 30 days


def backup_now():
    """Create timestamped backup of all DBs"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    now    = datetime.now(IST)
    stamp  = now.strftime("%Y%m%d_%H%M%S")
    backed = []

    dbs = [
        "data/chanakya_v3.db",
    ]

    for db_path in dbs:
        if not os.path.exists(db_path):
            continue
        try:
            db_name = os.path.basename(db_path).replace(".db","")
            bak_dir = os.path.join(BACKUP_DIR, db_name)
            os.makedirs(bak_dir, exist_ok=True)
            bak_file = os.path.join(bak_dir, f"{db_name}_{stamp}.db")

            # SQLite safe backup (using sqlite3 backup API)
            src  = sqlite3.connect(db_path)
            dest = sqlite3.connect(bak_file)
            src.backup(dest)
            src.close()
            dest.close()

            size = os.path.getsize(bak_file) // 1024
            backed.append({"db": db_name, "file": bak_file, "size_kb": size})
            logger.info(f"✅ Backup: {bak_file} ({size} KB)")
        except Exception as e:
            logger.error(f"Backup failed {db_path}: {e}")

    # Cleanup old backups
    cleaned = cleanup_old_backups()
    logger.info(f"🧹 Cleaned {cleaned} old backups")

    return {
        "success":   True,
        "timestamp": stamp,
        "backups":   backed,
        "cleaned":   cleaned,
    }


def cleanup_old_backups():
    """Remove backups older than KEEP_DAYS"""
    if not os.path.exists(BACKUP_DIR):
        return 0
    cleaned = 0
    cutoff  = time.time() - (KEEP_DAYS * 86400)
    for root, dirs, files in os.walk(BACKUP_DIR):
        for f in files:
            if not f.endswith(".db"):
                continue
            fpath = os.path.join(root, f)
            if os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                cleaned += 1
    return cleaned


def list_backups():
    """List all available backups"""
    if not os.path.exists(BACKUP_DIR):
        return []
    backups = []
    for root, dirs, files in os.walk(BACKUP_DIR):
        for f in sorted(files, reverse=True):
            if not f.endswith(".db"):
                continue
            fpath = os.path.join(root, f)
            backups.append({
                "file":    f,
                "path":    fpath,
                "size_kb": os.path.getsize(fpath) // 1024,
                "created": datetime.fromtimestamp(
                    os.path.getmtime(fpath), IST
                ).strftime("%Y-%m-%d %H:%M"),
            })
    return backups[:20]  # Last 20


def restore_backup(backup_path, target_db="data/chanakya_v3.db"):
    """Restore from a backup file"""
    if not os.path.exists(backup_path):
        return False, "Backup file not found"
    try:
        # Create safety backup before restore
        safety = target_db + ".before_restore"
        shutil.copy2(target_db, safety)
        # Restore
        src  = sqlite3.connect(backup_path)
        dest = sqlite3.connect(target_db)
        src.backup(dest)
        src.close()
        dest.close()
        logger.info(f"✅ Restored from {backup_path}")
        return True, "Restored successfully"
    except Exception as e:
        logger.error(f"Restore error: {e}")
        return False, str(e)


class BackupScheduler:
    """Auto backup at configured times"""
    def __init__(self):
        self.running  = False
        self._thread  = None
        self._last_bk = None
        # Backup times (IST hour)
        self.backup_hours = [6, 12, 18, 23]  # 6AM, 12PM, 6PM, 11PM

    def start(self):
        self.running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="BackupScheduler"
        )
        self._thread.start()
        logger.info("✅ Backup scheduler started")

    def stop(self):
        self.running = False

    def _loop(self):
        while self.running:
            try:
                now = datetime.now(IST)
                h   = now.hour
                day = now.date()
                key = f"{day}_{h}"

                if h in self.backup_hours and key != self._last_bk:
                    logger.info(f"🕐 Scheduled backup at {h}:00")
                    result = backup_now()
                    self._last_bk = key
                    logger.info(f"✅ Auto backup: {len(result['backups'])} DBs")

            except Exception as e:
                logger.error(f"Backup scheduler: {e}")

            time.sleep(300)  # Check every 5 minutes

scheduler = BackupScheduler()
