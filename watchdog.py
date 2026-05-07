#!/usr/bin/env python3
"""
Watchdog for telegram_secretary.py.

Runs as an independent process. Reads bot.pid + bot_heartbeat.txt
written by the main bot. If the heartbeat goes stale (i.e. the Python
interpreter inside the bot is hung), kills the bot process so that
start_secretary.bat can restart it.

Usage:
    python watchdog.py

Environment variables (inherited from start_secretary.bat):
    TELEGRAM_BOT_TOKEN   - used to notify the boss when bot is killed
    TELEGRAM_CHAT_ID     - boss chat id
"""

import json
import os
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# ─── Configuration ───────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PID_FILE = SCRIPT_DIR / "bot.pid"
HEARTBEAT_FILE = SCRIPT_DIR / "bot_heartbeat.txt"
LOG_FILE = SCRIPT_DIR / "watchdog.log"

CHECK_INTERVAL_SEC = 30      # how often to check heartbeat
STALE_THRESHOLD_SEC = 300    # 5 minutes — kill bot if no heartbeat for this long
STARTUP_GRACE_SEC = 60       # wait this long for bot to write PID file before giving up

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# SSL: try certifi if available, else fall back to default context
try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = ssl.create_default_context()


def log(msg):
    """Print + append to log file."""
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def notify_boss(text):
    """Send a Telegram message to the boss. Best-effort, never raises."""
    if not BOT_TOKEN or not CHAT_ID:
        log("notify_boss: BOT_TOKEN or CHAT_ID missing, skipping")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        data = urllib.parse.urlencode({
            "chat_id": CHAT_ID,
            "text": text,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
            resp = json.loads(r.read().decode("utf-8"))
            if not resp.get("ok"):
                log(f"notify_boss failed: {resp}")
    except Exception as e:
        log(f"notify_boss error: {e}")


def read_pid():
    """Return the bot PID if the file exists and contains a valid int."""
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def heartbeat_age():
    """Return seconds since heartbeat was last updated, or None if no file."""
    if not HEARTBEAT_FILE.exists():
        return None
    try:
        mtime = HEARTBEAT_FILE.stat().st_mtime
        return time.time() - mtime
    except Exception:
        return None


def is_process_alive(pid):
    """Check if a process with the given PID is alive (cross-platform)."""
    if pid is None or pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            # tasklist returns the PID line if it exists, else "INFO: No tasks..."
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
            return str(pid) in (r.stdout or "")
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


def kill_bot(pid):
    """Force-kill the bot process and its children."""
    log(f"Killing bot process PID={pid}...")
    try:
        if sys.platform == "win32":
            # /F = force, /T = kill child tree
            r = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, text=True, timeout=15,
            )
            log(f"taskkill exit={r.returncode}, stdout={r.stdout.strip()[:200]}, "
                f"stderr={r.stderr.strip()[:200]}")
            return r.returncode == 0
        else:
            import signal
            os.kill(pid, signal.SIGKILL)
            return True
    except Exception as e:
        log(f"kill_bot error: {e}")
        return False


def wait_for_pid(grace_sec):
    """Wait up to grace_sec for the bot to write its PID file."""
    deadline = time.time() + grace_sec
    while time.time() < deadline:
        pid = read_pid()
        if pid:
            return pid
        time.sleep(2)
    return None


def main():
    log("=" * 50)
    log("Watchdog starting")
    log(f"PID file: {PID_FILE}")
    log(f"Heartbeat file: {HEARTBEAT_FILE}")
    log(f"Stale threshold: {STALE_THRESHOLD_SEC}s, check interval: {CHECK_INTERVAL_SEC}s")
    log("=" * 50)

    # Wait for bot to start and write its PID
    pid = wait_for_pid(STARTUP_GRACE_SEC)
    if not pid:
        log(f"No bot PID found after {STARTUP_GRACE_SEC}s, exiting")
        return
    log(f"Watching bot PID={pid}")

    while True:
        try:
            time.sleep(CHECK_INTERVAL_SEC)

            # Bot might have been restarted by bat — reload PID
            current_pid = read_pid()
            if current_pid and current_pid != pid:
                log(f"Bot PID changed: {pid} -> {current_pid}")
                pid = current_pid

            # If bot process is gone, our job is done — let bat restart everything
            if not is_process_alive(pid):
                log(f"Bot process PID={pid} is no longer alive, watchdog exiting")
                return

            # Check heartbeat age
            age = heartbeat_age()
            if age is None:
                log("No heartbeat file yet, waiting...")
                continue

            if age > STALE_THRESHOLD_SEC:
                log(f"HEARTBEAT STALE: {age:.0f}s old (threshold {STALE_THRESHOLD_SEC}s)")
                log(f"Bot appears hung — killing PID={pid}")

                notify_boss(
                    f"⚠️ 老板，小花卡死了 ({age:.0f} 秒没心跳)，"
                    f"我（看门狗）现在强制重启她，请稍等～"
                )

                killed = kill_bot(pid)
                if killed:
                    log("Kill succeeded, watchdog exiting (bat will restart bot)")
                    # Clean up stale heartbeat so the next instance starts fresh
                    try:
                        HEARTBEAT_FILE.unlink()
                    except Exception:
                        pass
                    return
                else:
                    log("Kill failed, will retry next cycle")
                    # Don't exit — try again
            else:
                # Heartbeat is fresh — bot is healthy
                log(f"Heartbeat OK ({age:.0f}s old)")

        except KeyboardInterrupt:
            log("Watchdog interrupted (Ctrl+C), exiting")
            return
        except Exception as e:
            log(f"Watchdog loop error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
