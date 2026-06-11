#!/usr/bin/env python3
"""
Telegram AI Secretary — 远程遥控 Claude Code
通过 Telegram 和 AI 秘书对话，秘书自动调 Claude Code 执行编码任务。
支持语音消息：发送语音 → 自动转文字 → 交给 Claude 处理
支持图片/文件：发截图或文件 → 保存本地 → 交给 Claude 处理
"""

import hashlib
import json
import os
import queue
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

# Fix Windows console encoding for Chinese characters
if sys.platform == "win32":
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Add ffmpeg to PATH before importing pydub (it checks PATH at import time)
_FFMPEG_DIR = r"C:\Users\Admin23\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin"
if os.path.isdir(_FFMPEG_DIR):
    os.environ["PATH"] = _FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")

# Voice transcription imports
try:
    import speech_recognition as sr
    from pydub import AudioSegment
    VOICE_ENABLED = True
except ImportError:
    VOICE_ENABLED = False

# Groq Whisper (高精度语音识别)
try:
    from groq import Groq as GroqClient
    GROQ_ENABLED = True
except ImportError:
    GROQ_ENABLED = False

# SSL: use certifi CA bundle for proper certificate verification
import certifi
SSL_CTX = ssl.create_default_context(cafile=certifi.where())

# ─── Configuration ───────────────────────────────────────────────
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GCFB_GROUP_CHAT_ID = os.environ.get("GCFB_GROUP_CHAT_ID", "")  # GCFB CUSTOMER SERVICE 群
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
BOSS_USER_ID = CHAT_ID  # 老板的 user_id 等于私聊 chat_id
SCRIPT_DIR = Path(__file__).parent
MEMORY_FILE = SCRIPT_DIR / "memory.json"
SYSTEM_PROMPT_FILE = SCRIPT_DIR / "system_prompt.txt"
MAILBOX_FILE = SCRIPT_DIR.parent / "bot_mailbox.json"  # 小花↔小虾 共享留言板
CLAUDE_TIMEOUT = 600  # 10 minutes max per command
MAX_TURNS_HAIKU = 5    # simple chat
MAX_TURNS_SONNET = 50  # coding/general tasks
MAX_TURNS_OPUS = 75    # complex tasks
DEFAULT_MODEL = "sonnet"
DEFAULT_CWD = os.environ.get(
    "SECRETARY_CWD",
    str(Path.home() / "Documents" / "cluade code")
)
# Claude Code v2.1+ uses compiled binary (claude.exe) instead of Node.js cli.js
CLAUDE_EXE = os.environ.get(
    "CLAUDE_EXE",
    r"C:\Users\Admin23\nodejs\node_modules\@anthropic-ai\claude-code\bin\claude.exe"
)

# ffmpeg path for voice conversion
FFMPEG_DIR = os.environ.get(
    "FFMPEG_DIR",
    r"C:\Users\Admin23\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin"
)
FFMPEG_PATH = os.path.join(FFMPEG_DIR, "ffmpeg.exe")
FFPROBE_PATH = os.path.join(FFMPEG_DIR, "ffprobe.exe")
if VOICE_ENABLED:
    AudioSegment.converter = FFMPEG_PATH
    AudioSegment.ffprobe = FFPROBE_PATH

# Temp directory for received files
RECEIVED_DIR = SCRIPT_DIR / "received_files"
RECEIVED_DIR.mkdir(exist_ok=True)


def _clean_received_files(max_age_days=7):
    """Delete files in received_files/ older than max_age_days. Called on startup."""
    try:
        cutoff = time.time() - (max_age_days * 86400)
        count = 0
        for f in RECEIVED_DIR.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                count += 1
        if count:
            log(f"🧹 Cleaned {count} old file(s) from received_files/")
    except Exception as e:
        log(f"Clean received_files error (non-critical): {e}")

# ─── Self-Heal Configuration ────────────────────────────────────
CRASH_LOG_FILE = SCRIPT_DIR / "crash_log.txt"
HEAL_STATE_FILE = SCRIPT_DIR / "heal_state.json"
HEAL_BACKUP_FILE = SCRIPT_DIR / "telegram_secretary.py.heal_backup"
MAX_HEAL_ATTEMPTS = 3       # Max fix attempts per unique error
HEAL_COOLDOWN_SEC = 300     # 5 minutes between fix attempts
HEAL_CLI_TIMEOUT = 120      # 2 minutes max for Claude CLI fix
CONSECUTIVE_ERROR_LIMIT = 5 # Trigger safe mode after this many

# ─── Daily Report Configuration ──────────────────────────────────
# Send auto-report at 10:00 AM and 10:00 PM every day
REPORT_HOURS = {10, 22}   # 24-hour format

# LDS & Booking credentials (from .env, not hardcoded)
LDS_URL = "https://script.google.com/macros/s/AKfycbzTxymBxmmliLWpOdg-lh-Ev6tDKyjEf91wgTaDAtxx0gtEsZZrsL9rL9AFv7-XaySlew/exec?page=admin"
LDS_USER = os.environ.get("LDS_USER", "")
LDS_PASS = os.environ.get("LDS_PASS", "")
BOOKING_URL = "https://script.google.com/macros/s/AKfycbyq1uhgRek_xCtOeAeWnS6mKxoYI4FMSiezAHlGHB-GXkJNGIZNTaotIT76CmKNvoY_/exec?page=admin"
BOOKING_USER = os.environ.get("BOOKING_USER", "")
BOOKING_PASS = os.environ.get("BOOKING_PASS", "")
SS_PATH = str(SCRIPT_DIR / "desktop_now.png")
SS_SCRIPT = r"C:\Users\Admin23\AppData\Local\Temp\ss.ps1"


# ─── OAuth Token Note ────────────────────────────────────────────
# Claude Code v2.1+ uses OAuth tokens. The binary handles refresh
# internally (in-memory) even with expired tokens on disk. No need
# for proactive refresh — just robust retry with backoff on 401.


# ─── Parallel Task Queue ─────────────────────────────────────────
_task_queue = queue.Queue()
_task_counter_lock = threading.Lock()
_task_counter = [0]
_memory_lock = threading.Lock()  # Protects memory dict + save_memory() across threads
_current_proc = None             # Current Claude subprocess (for /cancel)
_current_proc_lock = threading.Lock()
_worker_thread = None            # Reference for watchdog
_last_auth_warn_ts = 0           # Cooldown for auth-error Telegram messages
_last_network_warn_ts = 0        # Cooldown for network-outage Telegram messages


def _next_task_code():
    """Generate A, B, C... Z, A1, B1... task codes."""
    with _task_counter_lock:
        n = _task_counter[0]
        _task_counter[0] += 1
    if n < 26:
        return chr(ord('A') + n)
    return chr(ord('A') + (n % 26)) + str(n // 26 + 1)


# ─── Telegram API ────────────────────────────────────────────────
def tg_api(method, params=None, retries=2):
    """Call Telegram Bot API with retry on network errors."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    for attempt in range(1, retries + 1):
        try:
            if params:
                data = urllib.parse.urlencode(params).encode("utf-8")
                req = urllib.request.Request(url, data=data)
            else:
                req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if attempt < retries:
                time.sleep(3)
            else:
                log(f"Telegram API error ({method}, {retries} attempts failed): {e}")
                return {"ok": False, "error": str(e)}


def clean_response(text):
    """Remove internal context headers that may leak into Claude's response."""
    # Strip context headers that were injected into the prompt
    headers = [
        r'\[永久知识库\].*?(?=\[当前消息\]|\Z)',
        r'\[最近对话记录\].*?(?=\[当前消息\]|\Z)',
        r'\[过去几天的对话摘要\].*?(?=\[当前消息\]|\Z)',
        r'\[当前消息\]\s*',
    ]
    for pattern in headers:
        text = re.sub(pattern, '', text, flags=re.DOTALL)
    # Also strip any leading [tag] lines that look like injected context
    text = re.sub(r'^\[\S+?\]\n', '', text, flags=re.MULTILINE)
    return text.strip()


def clean_markdown(text):
    """Strip markdown formatting from Claude's response for clean Telegram display."""
    # Remove markdown headers (# ## ### etc.)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Remove bold **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    # Remove italic *text* or _text_ (single)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'\1', text)
    # Remove code blocks ```...```
    text = re.sub(r'```[\s\S]*?```', '', text)
    # Remove inline code `text`
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Remove markdown links [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # Remove markdown table formatting (|---|---|)
    text = re.sub(r'^\|[-:\s|]+\|$', '', text, flags=re.MULTILINE)
    # Remove table row pipes: | cell | cell | → cell  cell
    text = re.sub(r'^\|\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*\|$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*\|\s*', '  ', text)
    # Remove horizontal rules (--- or ***)
    text = re.sub(r'^[\-\*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # Clean up excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def send_group_notification(text):
    """发送通知到 GCFB CUSTOMER SERVICE 群（顾客投诉/询问专用）"""
    if not GCFB_GROUP_CHAT_ID:
        log("GCFB_GROUP_CHAT_ID not configured, skipping group notification")
        return
    tg_api("sendMessage", {"chat_id": GCFB_GROUP_CHAT_ID, "text": text})


def send_msg(text, chat_id=None):
    """Send message to Telegram, auto-splitting long messages."""
    cid = chat_id or CHAT_ID
    # Strip leaked context headers, then clean markdown
    text = clean_response(text)
    text = clean_markdown(text)
    # Telegram limit is 4096 chars
    chunks = split_message(text, 4000)
    for chunk in chunks:
        tg_api("sendMessage", {
            "chat_id": cid,
            "text": chunk,
        })
        if len(chunks) > 1:
            time.sleep(0.5)  # avoid rate limit


def send_photo(file_path, caption=""):
    """Send an image file as inline photo via Telegram sendPhoto."""
    file_path = str(file_path)
    if not os.path.isfile(file_path):
        log(f"send_photo: file not found: {file_path}")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    boundary = "----SecretaryPhotoBoundary"
    file_name = os.path.basename(file_path)
    try:
        with open(file_path, "rb") as f:
            file_data = f.read()
        body = b""
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{CHAT_ID}\r\n'.encode()
        if caption:
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode()
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="photo"; filename="{file_name}"\r\n'.encode()
        body += b"Content-Type: image/jpeg\r\n\r\n"
        body += file_data
        body += f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(url, data=body)
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as r:
            resp = json.loads(r.read().decode("utf-8"))
            if resp.get("ok"):
                log(f"Photo sent: {file_name}")
                return True
            else:
                log(f"send_photo failed: {resp}")
                return send_file(file_path, caption)  # fallback to document
    except Exception as e:
        log(f"send_photo error: {e}")
        return False


def send_file(file_path, caption=""):
    """Send a file to user via Telegram sendDocument (multipart upload)."""
    file_path = str(file_path)
    if not os.path.isfile(file_path):
        log(f"send_file: file not found: {file_path}")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    boundary = "----SecretaryFileBoundary"
    file_name = os.path.basename(file_path)

    try:
        with open(file_path, "rb") as f:
            file_data = f.read()

        # Build multipart body
        body = b""
        # chat_id field
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{CHAT_ID}\r\n'.encode()
        # caption field (if any)
        if caption:
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode()
        # document field
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="document"; filename="{file_name}"\r\n'.encode()
        body += b"Content-Type: application/octet-stream\r\n\r\n"
        body += file_data
        body += f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(url, data=body)
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as r:
            resp = json.loads(r.read().decode("utf-8"))
            if resp.get("ok"):
                log(f"File sent: {file_name}")
                return True
            else:
                log(f"send_file failed: {resp}")
                return False
    except Exception as e:
        log(f"send_file error: {e}")
        return False


def split_message(text, max_len=4000):
    """Split long text into chunks, trying to break at newlines."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to break at last newline before max_len
        idx = text.rfind("\n", 0, max_len)
        if idx == -1:
            idx = max_len
        chunks.append(text[:idx])
        text = text[idx:].lstrip("\n")
    return chunks


# ─── Typing Indicator ─────────────────────────────────────────────
class TypingIndicator:
    """Send 'typing...' action to Telegram while Claude is processing."""

    def __init__(self):
        self._running = False
        self._thread = None
        self._chat_id = CHAT_ID

    def start(self, chat_id=None):
        self._chat_id = chat_id or CHAT_ID
        self._running = True
        self._send_loop()

    def _send_loop(self):
        if self._running:
            tg_api("sendChatAction", {"chat_id": self._chat_id, "action": "typing"})
            self._thread = threading.Timer(4.0, self._send_loop)
            self._thread.daemon = True
            self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.cancel()
            self._thread = None


# ─── File Download from Telegram ──────────────────────────────────
def download_telegram_file(file_id, suffix=None, filename=None):
    """Download any file from Telegram by file_id. Returns local path or None."""
    resp = tg_api("getFile", {"file_id": file_id})
    if not resp.get("ok"):
        return None
    tg_file_path = resp["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{tg_file_path}"

    if filename:
        local_path = str(RECEIVED_DIR / filename)
    elif suffix:
        ts = time.strftime("%Y%m%d_%H%M%S")
        local_path = str(RECEIVED_DIR / f"file_{ts}{suffix}")
    else:
        ext = os.path.splitext(tg_file_path)[1] or ".bin"
        ts = time.strftime("%Y%m%d_%H%M%S")
        local_path = str(RECEIVED_DIR / f"file_{ts}{ext}")

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as r:
            with open(local_path, "wb") as f:
                f.write(r.read())
        log(f"Downloaded file: {local_path}")
        return local_path
    except Exception as e:
        log(f"File download error: {e}")
        return None


# ─── Voice Transcription ────────────────────────────────────────
def download_voice(file_id):
    """Download voice message from Telegram and return local path."""
    resp = tg_api("getFile", {"file_id": file_id})
    if not resp.get("ok"):
        return None
    file_path = resp["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

    tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
            tmp.write(r.read())
        tmp.close()
        return tmp.name
    except Exception as e:
        log(f"Voice download error: {e}")
        return None


def _recognize_with_timeout(recognizer, audio_data, lang, timeout=30):
    """Run speech recognition with a timeout to prevent hanging."""
    result = [None]
    error = [None]

    def _worker():
        try:
            result[0] = recognizer.recognize_google(audio_data, language=lang)
        except sr.UnknownValueError:
            pass
        except Exception as e:
            error[0] = e

    t = threading.Thread(target=_worker)
    t.daemon = True
    t.start()
    t.join(timeout)

    if t.is_alive():
        log(f"Speech recognition timed out ({lang}, {timeout}s)")
        return None
    if error[0]:
        log(f"Speech recognition error ({lang}): {error[0]}")
        return None
    return result[0]


def _transcribe_with_groq(ogg_path):
    """Use Groq Whisper-large-v3 for transcription. Handles Chinese + English + Malay mixed."""
    if not GROQ_ENABLED or not GROQ_API_KEY:
        return None
    try:
        client = GroqClient(api_key=GROQ_API_KEY)
        with open(ogg_path, "rb") as f:
            result = client.audio.transcriptions.create(
                file=(os.path.basename(ogg_path), f.read()),
                model="whisper-large-v3",
                response_format="text",
                language=None,  # auto-detect: handles Chinese/English/Malay mix
            )
        text = str(result).strip() if result else ""
        if text:
            log(f"Groq Whisper recognized: {text[:80]}...")
        return text or None
    except Exception as e:
        log(f"Groq transcription error: {e}")
        return None


def _transcribe_with_google(ogg_path):
    """Fallback: Google Speech Recognition (free, less accurate)."""
    if not VOICE_ENABLED:
        return None
    wav_path = ogg_path.replace(".ogg", ".wav")
    try:
        audio = AudioSegment.from_ogg(ogg_path)
        audio.export(wav_path, format="wav")
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
        for lang in ["zh-CN", "en-US"]:
            text = _recognize_with_timeout(recognizer, audio_data, lang, timeout=30)
            if text:
                log(f"Google STT recognized ({lang}): {text[:60]}...")
                return text
        return None
    except Exception as e:
        log(f"Google STT error: {e}")
        return None
    finally:
        try:
            os.unlink(wav_path)
        except Exception:
            pass


def transcribe_voice(ogg_path):
    """Convert OGG voice to text. Uses Groq Whisper first, falls back to Google STT."""
    try:
        # 优先用 Groq Whisper (高精度，支持华语/英语/马来语混合)
        text = _transcribe_with_groq(ogg_path)
        if text:
            return text
        # 备用: Google Speech Recognition
        log("Groq failed or unavailable, trying Google STT...")
        text = _transcribe_with_google(ogg_path)
        return text
    finally:
        # 清理原始 OGG 文件
        try:
            os.unlink(ogg_path)
        except Exception:
            pass


# ─── Self-Heal System (v2) ──────────────────────────────────────
#
# Error Classification:
#   🔧 CODE_BUG   — SyntaxError, NameError, TypeError, etc. → Claude fixes code
#   📦 MISSING_DEP — ImportError, ModuleNotFoundError → auto pip install
#   🌐 ENVIRONMENT — 401 auth, timeout, network, config → retry + notify boss
#   💾 RESOURCE    — disk full, MemoryError → cleanup + notify boss
#
# Safety Net:
#   1. Backup before any fix
#   2. py_compile check after fix
#   3. import test after fix
#   4. Rollback if fix breaks things

def load_heal_state():
    """Load heal state tracking from JSON file."""
    if HEAL_STATE_FILE.exists():
        try:
            return json.loads(HEAL_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"errors": {}}


def save_heal_state(state):
    """Save heal state tracking to JSON file."""
    # Clean up entries older than 7 days
    errors = state.get("errors", {})
    cutoff = (datetime.now().timestamp()) - (7 * 86400)
    for sig in list(errors.keys()):
        last = errors[sig].get("last_attempt", "")
        if last:
            try:
                if datetime.fromisoformat(last).timestamp() < cutoff:
                    del errors[sig]
            except Exception:
                pass
    HEAL_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def get_error_signature(stderr_text):
    """Generate a normalized signature for an error to track unique errors."""
    if not stderr_text:
        return "empty_error"
    normalized = re.sub(r'line \d+', 'line N', stderr_text)
    normalized = re.sub(r'\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}', 'TIMESTAMP', normalized)
    normalized = re.sub(r'\d{2}/\d{2}/\d{4}', 'DATE', normalized)
    normalized = re.sub(r'\d{2}:\d{2}:\d{2}', 'TIME', normalized)
    normalized = re.sub(r'0x[0-9a-fA-F]+', '0xADDR', normalized)
    normalized = re.sub(r'PID\s*\d+', 'PID N', normalized)
    normalized = normalized.strip()[-500:]
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:12]


def classify_error(stderr_text):
    """Classify error into categories. Returns (category, detail).
    Categories: 'code_bug', 'missing_dep', 'environment', 'resource'."""
    if not stderr_text:
        return "environment", "empty stderr"

    lower = stderr_text.lower()

    # 📦 Missing dependency — can auto-fix with pip install
    dep_match = re.search(r"(?:ModuleNotFoundError|ImportError).*?['\"](\S+?)['\"]", stderr_text)
    if dep_match or "no module named" in lower:
        module_name = dep_match.group(1) if dep_match else "unknown"
        return "missing_dep", module_name

    # 💾 Resource issues — cleanup, don't fix code
    if any(kw in lower for kw in ["memoryerror", "out of memory", "no space left",
                                    "disk full", "errno 28", "errno 12"]):
        return "resource", "system resource exhaustion"

    # 🌐 Environment / network / auth — retry, don't fix code
    env_keywords = [
        "authentication_error", "401", "403", "connectionerror", "timeout",
        "econnreset", "econnrefused", "etimedout", "enotfound",
        "socket hang up", "network", "ssl", "certificate",
        "rate limit", "429", "529", "overloaded",
        "permission denied", "access denied",
    ]
    if any(kw in lower for kw in env_keywords):
        return "environment", next(kw for kw in env_keywords if kw in lower)

    # 🔧 Code bug — everything else (SyntaxError, NameError, TypeError, etc.)
    return "code_bug", stderr_text.strip().split('\n')[-1][:100]


def can_attempt_heal(signature, state):
    """Check if we can attempt to fix this error (respects limits and cooldown)."""
    errors = state.get("errors", {})
    if signature not in errors:
        return True
    info = errors[signature]
    if info.get("count", 0) >= MAX_HEAL_ATTEMPTS:
        return False
    last = info.get("last_attempt", "")
    if last:
        try:
            elapsed = (datetime.now() - datetime.fromisoformat(last)).total_seconds()
            if elapsed < HEAL_COOLDOWN_SEC:
                return False
        except Exception:
            pass
    return True


def parse_crash_log():
    """Parse crash_log.txt and extract the most recent crash info."""
    if not CRASH_LOG_FILE.exists():
        return None
    try:
        content = CRASH_LOG_FILE.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    if "===CRASH_START===" not in content:
        return None

    blocks = content.split("===CRASH_START===")
    if len(blocks) < 2:
        return None
    last_block = blocks[-1]
    crash_info = {"exit_code": "unknown", "stderr": "", "timestamp": ""}

    ts_match = re.search(r'timestamp=(.+)', last_block)
    if ts_match:
        crash_info["timestamp"] = ts_match.group(1).strip()
    ec_match = re.search(r'exit_code=(\S+)', last_block)
    if ec_match:
        crash_info["exit_code"] = ec_match.group(1).strip()
    stderr_match = re.search(r'--- stderr ---\s*\n(.*?)(?:===CRASH_END===|\Z)', last_block, re.DOTALL)
    if stderr_match:
        crash_info["stderr"] = stderr_match.group(1).strip()

    # Skip clean kills
    if crash_info["exit_code"] == "-1" and not crash_info["stderr"]:
        return None
    if crash_info["stderr"] or crash_info["exit_code"] not in ("0", "unknown"):
        return crash_info
    return None


# ─── Safety Net: backup / verify / rollback ─────────────────────
def _backup_bot_file():
    """Create backup before any fix attempt."""
    bot_file = SCRIPT_DIR / "telegram_secretary.py"
    try:
        shutil.copy2(bot_file, HEAL_BACKUP_FILE)
        log(f"Self-heal: Backup created → {HEAL_BACKUP_FILE.name}")
        return True
    except Exception as e:
        log(f"Self-heal: Backup failed: {e}")
        return False


def _verify_bot_file():
    """Verify bot file after fix: syntax check + import test.
    Returns (ok: bool, error: str)."""
    bot_file = str(SCRIPT_DIR / "telegram_secretary.py")
    # 1) Syntax check
    try:
        import py_compile
        py_compile.compile(bot_file, doraise=True)
    except py_compile.PyCompileError as e:
        return False, f"语法错误: {e}"

    # 2) Import test (load as module, check main symbols exist)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_heal_test", bot_file)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # Check critical functions exist
        for name in ["main", "run_claude", "send_msg", "task_worker", "load_memory"]:
            if not hasattr(mod, name):
                return False, f"关键函数 {name} 丢失"
    except Exception as e:
        return False, f"导入测试失败: {str(e)[:200]}"

    return True, "OK"


def _rollback_bot_file():
    """Restore bot file from backup."""
    bot_file = SCRIPT_DIR / "telegram_secretary.py"
    if HEAL_BACKUP_FILE.exists():
        try:
            shutil.copy2(HEAL_BACKUP_FILE, bot_file)
            log("Self-heal: ROLLED BACK to backup")
            return True
        except Exception as e:
            log(f"Self-heal: Rollback failed: {e}")
    return False


# ─── Fix Handlers per Category ──────────────────────────────────
def _fix_missing_dep(module_name):
    """Auto-install missing Python package. Returns (success, summary)."""
    # Map common module names to pip package names
    pip_map = {
        "cv2": "opencv-python",
        "PIL": "Pillow",
        "sklearn": "scikit-learn",
        "yaml": "pyyaml",
        "bs4": "beautifulsoup4",
    }
    pkg = pip_map.get(module_name, module_name)
    log(f"Self-heal: Auto-installing missing package: {pkg}")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0:
            return True, f"自动安装了 {pkg}"
        return False, f"pip install {pkg} 失败: {result.stderr[:200]}"
    except Exception as e:
        return False, f"安装出错: {str(e)[:200]}"


def _fix_code_bug(crash_info):
    """Call Claude CLI to fix a code bug. Returns (success, summary).
    Includes safety net: backup → fix → verify → rollback if broken."""
    # Step 1: Backup
    if not _backup_bot_file():
        return False, "无法创建备份，放弃修复"

    # Step 2: Call Claude to fix
    stderr_snippet = crash_info["stderr"][:2000]
    bot_file = os.path.abspath(str(SCRIPT_DIR / "telegram_secretary.py"))

    prompt = (
        f"你是 Telegram 秘书机器人（小花）的维修工。\n"
        f"这个机器人是一个 2000+ 行的 Python 文件，通过 Telegram Bot API 接收消息，"
        f"调用 Claude Code CLI 处理任务，有语音转文字、图片处理、自动汇报等功能。\n\n"
        f"上次运行崩溃了，错误信息如下：\n\n"
        f"退出码: {crash_info['exit_code']}\n"
        f"错误输出:\n{stderr_snippet}\n\n"
        f"请分析错误原因，然后直接修复文件: {bot_file}\n\n"
        f"重要规则：\n"
        f"- 只修复导致崩溃的问题，不要改其他功能\n"
        f"- 不要删除任何现有功能\n"
        f"- 不要改变函数签名（参数）\n"
        f"- 确保修复后代码语法正确\n"
        f"- 修复后简要说明改了什么"
    )

    cmd = [
        CLAUDE_EXE,
        "-p", prompt,
        "--output-format", "text",
        "--model", "sonnet",
        "--max-turns", "10",
        "--dangerously-skip-permissions",
    ]

    try:
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)  # let claude.exe use credentials.json (auto-refreshed)
        result = subprocess.run(
            cmd, cwd=str(SCRIPT_DIR),
            capture_output=True, text=True, timeout=HEAL_CLI_TIMEOUT,
            encoding="utf-8", errors="replace", shell=False, env=env,
        )
        output = result.stdout.strip()
        if result.returncode != 0 or not output:
            err = result.stderr.strip()[:200] if result.stderr else "no output"
            _rollback_bot_file()
            return False, f"Claude CLI 返回错误: {err}"
    except subprocess.TimeoutExpired:
        _rollback_bot_file()
        return False, "修复超时（2分钟）"
    except Exception as e:
        _rollback_bot_file()
        return False, f"修复出错: {str(e)[:200]}"

    # Step 3: Verify the fix
    ok, verify_msg = _verify_bot_file()
    if not ok:
        log(f"Self-heal: Fix BROKE the code! {verify_msg}")
        _rollback_bot_file()
        return False, f"Claude 的修复破坏了代码（{verify_msg}），已回滚"

    summary = output[:300]
    log(f"Self-heal: Fix verified OK")
    return True, summary


def archive_crash_log():
    """Clear crash_log.txt after processing."""
    try:
        if CRASH_LOG_FILE.exists():
            CRASH_LOG_FILE.write_text(
                f"[Archived at {time.strftime('%Y-%m-%d %H:%M:%S')}]\n",
                encoding="utf-8",
            )
    except Exception as e:
        log(f"archive_crash_log error: {e}")


def log_error_to_disk(error):
    """Write a runtime error to crash_log.txt for self-heal to pick up on next restart."""
    try:
        tb = traceback.format_exc()
        with open(str(CRASH_LOG_FILE), "a", encoding="utf-8") as f:
            f.write("===CRASH_START===\n")
            f.write(f"timestamp={time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("exit_code=runtime_error\n")
            f.write("--- stderr ---\n")
            f.write(f"{type(error).__name__}: {error}\n")
            f.write(f"{tb}\n")
            f.write("===CRASH_END===\n")
    except Exception:
        pass


def self_heal():
    """Main self-heal entry point (v2). Called at startup.
    Classifies error → picks the right fix strategy → verifies → reports."""
    crash_info = parse_crash_log()
    if not crash_info:
        log("Self-heal: No crash detected, clean startup.")
        return

    stderr_text = crash_info["stderr"]
    stderr_short = stderr_text[:200] if stderr_text else "(no stderr)"
    log(f"Self-heal: Crash detected! Exit code={crash_info['exit_code']}")

    # ── Step 1: Classify the error ──
    category, detail = classify_error(stderr_text)
    log(f"Self-heal: Category={category}, Detail={detail[:80]}")

    # ── Step 2: Handle by category ──

    if category == "environment":
        # 🌐 Network/auth/config — NOT a code bug, just report
        log("Self-heal: Environment error — skipping code fix")
        try:
            send_msg(
                f"老板，上次出了网络/环境问题（不是代码 bug）\n"
                f"类型: {detail}\n"
                f"错误: {stderr_short}\n\n"
                f"这种问题通常会自己恢复，我继续正常运行 👍"
            )
        except Exception:
            pass
        archive_crash_log()
        return

    if category == "resource":
        # 💾 Resource — cleanup + report
        log("Self-heal: Resource error — attempting cleanup")
        try:
            _clean_received_files(max_age_days=1)  # Aggressive cleanup
            _trim_log_file()
            send_msg(
                f"老板，上次因为系统资源问题崩溃了\n"
                f"详情: {detail}\n\n"
                f"已自动清理缓存文件，继续运行"
            )
        except Exception:
            pass
        archive_crash_log()
        return

    if category == "missing_dep":
        # 📦 Missing dependency — auto pip install
        log(f"Self-heal: Missing dependency — auto-installing: {detail}")
        try:
            send_msg(f"检测到缺少依赖包 {detail}，正在自动安装...")
        except Exception:
            pass
        success, summary = _fix_missing_dep(detail)
        try:
            if success:
                send_msg(f"✅ {summary}，继续正常运行")
            else:
                send_msg(f"❌ 依赖安装失败: {summary}\n需要老板手动安装")
        except Exception:
            pass
        archive_crash_log()
        log(f"Self-heal: dep install {'OK' if success else 'FAIL'} — {summary}")
        return

    # ── category == "code_bug" ──
    # 🔧 Code bug — Claude fixes with safety net
    state = load_heal_state()
    signature = get_error_signature(stderr_text)

    if not can_attempt_heal(signature, state):
        attempts = state.get("errors", {}).get(signature, {}).get("count", 0)
        log(f"Self-heal: Skip fix (sig={signature}, attempts={attempts}/{MAX_HEAL_ATTEMPTS})")
        try:
            send_msg(
                f"老板，这个代码错误修了{attempts}次还是不行\n"
                f"错误: {stderr_short}\n\n"
                f"需要你亲自看看 🔧"
            )
        except Exception:
            pass
        archive_crash_log()
        return

    try:
        send_msg(
            f"检测到代码 bug（{crash_info['exit_code']}）\n"
            f"错误: {stderr_short}\n\n"
            f"正在备份 → 修复 → 验证... 🔧"
        )
    except Exception:
        pass

    success, summary = _fix_code_bug(crash_info)

    # Update heal state
    errors = state.setdefault("errors", {})
    if signature not in errors:
        errors[signature] = {
            "count": 0,
            "first_seen": datetime.now().isoformat(),
            "stderr_snippet": stderr_text[:100],
        }
    errors[signature]["count"] = errors[signature].get("count", 0) + 1
    errors[signature]["last_attempt"] = datetime.now().isoformat()
    errors[signature]["last_result"] = "success" if success else "failed"
    save_heal_state(state)

    try:
        if success:
            send_msg(f"✅ 自动修复完成（已验证语法+导入）\n修复: {summary[:500]}")
        else:
            send_msg(f"❌ 自动修复失败: {summary[:300]}\n代码已回滚到修复前的版本，不会更糟")
    except Exception:
        pass

    archive_crash_log()
    log(f"Self-heal: {'SUCCESS' if success else 'FAILED'} — {summary[:100]}")


def run_diagnose():
    """Run self-diagnostics on demand (called by /diagnose command).
    Checks: syntax, imports, config, connectivity, disk space."""
    results = []

    # 1) Syntax check
    bot_file = str(SCRIPT_DIR / "telegram_secretary.py")
    try:
        import py_compile
        py_compile.compile(bot_file, doraise=True)
        results.append("✅ 代码语法正常")
    except Exception as e:
        results.append(f"❌ 代码语法错误: {e}")

    # 2) Key config check
    config_ok = True
    if not BOT_TOKEN:
        results.append("❌ BOT_TOKEN 未设置")
        config_ok = False
    if not CHAT_ID:
        results.append("❌ CHAT_ID 未设置")
        config_ok = False
    if not SUPABASE_SERVICE_KEY:
        results.append("⚠️ SUPABASE_SERVICE_KEY 未设置")
    if not GROQ_API_KEY:
        results.append("⚠️ GROQ_API_KEY 未设置")
    if config_ok:
        results.append("✅ 核心配置正常")

    # 3) Claude CLI check
    try:
        if os.path.isfile(CLAUDE_EXE):
            results.append("✅ Claude CLI 存在")
        else:
            results.append(f"❌ Claude CLI 不存在: {CLAUDE_EXE}")
    except Exception:
        results.append("❌ Claude CLI 检查失败")

    # 4) Memory file check
    try:
        data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        h_count = len(data.get("history", []))
        results.append(f"✅ memory.json 正常 ({h_count} 条记忆)")
    except Exception as e:
        results.append(f"❌ memory.json 损坏: {e}")

    # 5) Disk space check
    try:
        import shutil as _sh
        total, used, free = _sh.disk_usage(str(SCRIPT_DIR))
        free_gb = free / (1024**3)
        if free_gb < 1:
            results.append(f"⚠️ 磁盘空间不足: {free_gb:.1f}GB")
        else:
            results.append(f"✅ 磁盘空间: {free_gb:.1f}GB 可用")
    except Exception:
        results.append("⚠️ 磁盘空间无法检测")

    # 6) Telegram API connectivity
    try:
        resp = tg_api("getMe")
        if resp.get("ok"):
            results.append("✅ Telegram API 连接正常")
        else:
            results.append("❌ Telegram API 异常")
    except Exception:
        results.append("❌ Telegram API 无法连接")

    # 7) Worker thread status
    if _worker_thread and _worker_thread.is_alive():
        results.append("✅ Worker 线程正常")
    else:
        results.append("❌ Worker 线程已停止")

    # 8) Heal state summary
    state = load_heal_state()
    err_count = len(state.get("errors", {}))
    results.append(f"📊 历史修复记录: {err_count} 个错误签名")

    return "\n".join(results)


# ─── Memory ──────────────────────────────────────────────────────
def load_memory():
    """Load memory, auto-recover from backup if corrupted."""
    # 尝试主文件
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"⚠️ memory.json corrupted: {e}")

    # 主文件失败或不存在 → 尝试备份
    bak_file = MEMORY_FILE.with_suffix(".json.bak")
    if bak_file.exists():
        try:
            data = json.loads(bak_file.read_text(encoding="utf-8"))
            log("✅ Recovered memory from .bak file")
            try:
                send_msg("⚠️ 老板，memory.json 损坏了，我从备份恢复了记忆，可能丢失最近一条对话。")
            except Exception:
                pass
            return data
        except Exception:
            log("❌ Backup also corrupted!")

    # 全部失败 → 空记忆
    return {
        "tasks": [],
        "notes": [],
        "history": [],
        "current_model": DEFAULT_MODEL,
        "cwd": DEFAULT_CWD,
        "knowledge_base": {
            "people": {},
            "systems": {},
            "rules": [],
            "lessons": []
        }
    }


def save_memory(memory):
    """Save memory with atomic write and rolling backup. Thread-safe."""
    with _memory_lock:
        content = json.dumps(memory, ensure_ascii=False, indent=2)

        # 1) 备份当前文件
        bak_file = MEMORY_FILE.with_suffix(".json.bak")
        if MEMORY_FILE.exists():
            try:
                shutil.copy2(MEMORY_FILE, bak_file)
            except Exception:
                pass

        # 2) 原子写入：先写临时文件，再 rename（防写到一半损坏）
        tmp_file = MEMORY_FILE.with_suffix(".json.tmp")
        tmp_file.write_text(content, encoding="utf-8")
        tmp_file.replace(MEMORY_FILE)


# ─── Bot Mailbox (小花↔小虾 共享留言板) ──────────────────────────────
def _load_mailbox():
    """Load shared mailbox file."""
    try:
        if MAILBOX_FILE.exists():
            return json.loads(MAILBOX_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"xiaohong_to_xiaoxia": [], "xiaoxia_to_xiaohong": [], "last_updated": ""}


def _save_mailbox(data):
    """Save shared mailbox file atomically."""
    data["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tmp = MAILBOX_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(MAILBOX_FILE)


def write_to_xiaoxia(message, msg_type="INFO", priority="normal"):
    """小花 → 小虾：写留言到共享文件。
    msg_type: INFO | ALERT | TASK | HANDOFF
    priority: high | normal | low
    """
    mb = _load_mailbox()
    mb["xiaohong_to_xiaoxia"].append({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "type": msg_type,
        "priority": priority,
        "msg": message
    })
    # 只保留最近20条
    mb["xiaohong_to_xiaoxia"] = mb["xiaohong_to_xiaoxia"][-20:]
    _save_mailbox(mb)
    log(f"Mailbox → 小虾 [{msg_type}/{priority}]: {message[:60]}")


def read_from_xiaoxia():
    """小花 读取 小虾 留下的消息，读完清空。"""
    mb = _load_mailbox()
    msgs = mb.get("xiaoxia_to_xiaohong", [])
    if msgs:
        mb["xiaoxia_to_xiaohong"] = []
        _save_mailbox(mb)
    return msgs


def read_mailbox_status():
    """返回留言板当前状态摘要（双向）。"""
    mb = _load_mailbox()
    to_xia = mb.get("xiaohong_to_xiaoxia", [])
    to_hua = mb.get("xiaoxia_to_xiaohong", [])
    lines = [f"留言板更新时间：{mb.get('last_updated','未知')}"]
    if to_xia:
        lines.append(f"小花→小虾 ({len(to_xia)}条未读)：")
        for m in to_xia[-3:]:
            lines.append(f"  [{m['time']}] {m['msg'][:80]}")
    else:
        lines.append("小花→小虾：无留言")
    if to_hua:
        lines.append(f"小虾→小花 ({len(to_hua)}条)：")
        for m in to_hua[-3:]:
            lines.append(f"  [{m['time']}] {m['msg'][:80]}")
    else:
        lines.append("小虾→小花：无留言")
    return "\n".join(lines)


def check_xiaoxia_mailbox():
    """检查小虾发来的消息，转发给老板。每小时自动调用一次。"""
    msgs = read_from_xiaoxia()
    if not msgs:
        return
    lines = ["📬 小虾发来消息："]
    for m in msgs:
        mtype = m.get("type", "INFO")
        priority = m.get("priority", "normal")
        icon = "🚨" if priority == "high" else ("📋" if mtype == "TASK" else "ℹ️")
        lines.append(f"{icon} [{m['time'][5:16]}] {m['msg']}")
    send_msg("\n".join(lines))
    log(f"Forwarded {len(msgs)} messages from 小虾 to boss")


_ERROR_PATTERNS = [
    "Failed to authenticate",
    "authentication_error",
    "API Error: 401",
    "Invalid authentication credentials",
    "（重试后仍无输出）",
    "CLI 启动异常",
]


def _clean_history_errors(memory):
    """Remove useless error entries from history (e.g. 401 auth failures).
    Called once on startup to save token waste."""
    history = memory.get("history", [])
    before = len(history)
    cleaned = [h for h in history if not any(p in h for p in _ERROR_PATTERNS)]
    if len(cleaned) < before:
        memory["history"] = cleaned
        log(f"🧹 Cleaned {before - len(cleaned)} error entries from history")
        save_memory(memory)


def add_history(memory, user_msg, response):
    """Add conversation summary to memory. Uses tiered memory:
    - history: last 50 detailed entries (recent conversations)
    - daily_summaries: compressed daily summaries, kept for 30 days
    When old entries get pushed out, they're compressed into daily summaries.
    Skips saving error responses (401, empty output, etc.) to keep history clean.
    """
    # Skip saving error responses — they waste token context
    if any(p in response for p in _ERROR_PATTERNS):
        log("Skipped saving error response to history")
        return

    today = time.strftime("%m/%d")
    ts = time.strftime("%m/%d %H:%M")
    user_short = user_msg[:200].replace("\n", " ")
    resp_short = response[:300].replace("\n", " ")
    entry = f"[{ts}] 老板: {user_short} → 秘书: {resp_short}"

    history = memory.setdefault("history", [])
    history.append(entry)

    # Before trimming, compress old entries into daily summaries
    if len(history) > 100:
        # Entries that will be removed
        overflow = history[:-100]
        _compress_to_daily(memory, overflow)
        memory["history"] = history[-100:]

    # Clean up daily summaries older than 30 days
    summaries = memory.get("daily_summaries", {})
    if len(summaries) > 30:
        # Keep only 30 most recent days
        sorted_days = sorted(summaries.keys())
        for old_day in sorted_days[:-30]:
            del summaries[old_day]


def _compress_to_daily(memory, entries):
    """Compress history entries into daily summaries."""
    summaries = memory.setdefault("daily_summaries", {})
    for entry in entries:
        # Extract date from entry like "[02/28 11:25] 老板: ..."
        match = re.match(r'\[(\d{2}/\d{2})', entry)
        if match:
            day = match.group(1)
        else:
            day = time.strftime("%m/%d")

        if day not in summaries:
            summaries[day] = {"topics": [], "count": 0}
        # Extract the short topic (user's message part)
        topic_match = re.search(r'老板: (.+?) →', entry)
        if topic_match:
            topic = topic_match.group(1).strip()[:40]
            # Avoid duplicate topics
            if topic not in summaries[day]["topics"]:
                summaries[day]["topics"].append(topic)
                # Keep max 10 topics per day
                summaries[day]["topics"] = summaries[day]["topics"][-10:]
        summaries[day]["count"] += 1


def add_to_knowledge_base(memory, category, key, value):
    """Add or update a fact in the permanent knowledge base."""
    kb = memory.setdefault("knowledge_base", {
        "people": {}, "systems": {}, "rules": [], "lessons": []
    })
    if category in ("people", "systems"):
        kb[category][key] = value
    elif category in ("rules", "lessons"):
        target = kb[category]
        entry = f"{key}: {value}" if key else value
        if entry not in target:
            target.append(entry)
            # Keep last 20 rules/lessons
            kb[category] = target[-20:]


# ─── Smart Model Selection ───────────────────────────────────────
def auto_select_model(text, memory):
    """Automatically select the best model based on task complexity.
    Returns (model_name, reason).
    If user manually set a model via /model command, respect that (manual_model flag).
    """
    # If user manually locked a model, respect it
    if memory.get("manual_model"):
        m = memory.get("current_model", DEFAULT_MODEL)
        return m, "manual"

    text_lower = text.lower().strip()
    text_len = len(text_lower)

    # ── Check if this is a CONTINUATION of previous task ──
    # "好的"、"继续"、"ok" etc. often mean "continue the previous complex task"
    continuation_words = ["继续", "好的", "ok", "好", "收到", "了解", "嗯", "继续处理", "继续做"]
    prev_task = memory.get("current_task", {})
    is_continuation = (
        text_len < 15
        and any(w in text_lower for w in continuation_words)
    )
    if is_continuation:
        # Use sonnet for continuations — they're usually follow-ups to coding tasks
        return "sonnet", "continuation"

    # ── HAIKU: greetings + simple questions that don't need coding ──
    haiku_greetings = [
        "你好", "早安", "午安", "晚安", "嗨", "hi", "hello", "hey",
        "谢谢", "在吗", "在不在", "忙吗", "干嘛", "做什么",
        "没事", "不用了", "算了", "没问题", "可以了", "就这样",
        "拜拜", "再见", "晚安", "辛苦了", "不错",
    ]
    for g in haiku_greetings:
        if text_lower == g or (text_len < 8 and g in text_lower):
            return "haiku", "simple_chat"

    # Simple status/query questions → haiku (no coding needed)
    haiku_queries = [
        "几点", "什么时候", "今天几号", "星期几", "天气",
        "检查pm2", "查pm2", "pm2状态",
        "今日预约", "预约多少", "有多少预约",
        "打卡", "谁打卡了", "考勤",
    ]
    for q in haiku_queries:
        if q in text_lower and text_len < 30:
            return "haiku", "simple_query"

    # Very short messages with no action keywords → haiku
    if text_len < 6 and not any(w in text_lower for w in ["查", "改", "做", "帮", "看", "写", "修", "加", "删", "建"]):
        return "haiku", "very_short"

    # ── OPUS: only truly complex tasks needing deep reasoning ──
    # Keep this list TIGHT — opus is 3-5x slower than sonnet
    opus_keywords = [
        # Architecture & deep analysis only
        "架构", "重构", "技术选型",
        "深入分析", "全面检查", "彻底检查",
        # Complex multi-system debugging
        "一直报错", "找不到原因",
        # Full system audit
        "整个系统", "从头到尾",
        # Code review
        "代码审查", "代码质量",
    ]
    for kw in opus_keywords:
        if kw in text_lower:
            return "opus", "complex_task"

    # Only very long messages → opus (raised threshold)
    if text_len > 400:
        return "opus", "long_request"

    # ── SONNET: everything else (balanced default) ──
    return "sonnet", "default"


# ─── Claude Code ─────────────────────────────────────────────────
_system_prompt_cache = {"text": None, "mtime": 0}


def load_system_prompt():
    """Load system prompt from file (cached, reloads on file change)."""
    if SYSTEM_PROMPT_FILE.exists():
        mtime = SYSTEM_PROMPT_FILE.stat().st_mtime
        if mtime != _system_prompt_cache["mtime"]:
            _system_prompt_cache["text"] = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
            _system_prompt_cache["mtime"] = mtime
        return _system_prompt_cache["text"]
    return "你是AI秘书，用中文回复，像真人一样自然。"


def run_claude(prompt, memory, continue_session=True):
    """Run claude CLI and return the response text."""
    # Auto-select model based on task complexity
    model, reason = auto_select_model(prompt, memory)
    cwd = memory.get("cwd", DEFAULT_CWD)
    system_prompt = load_system_prompt()

    # Build context from tiered memory (skip if continuing session — already has context)
    if not continue_session:
        context_parts = []

        # Layer 0: Knowledge base — permanent facts about people, systems, rules, lessons
        kb = memory.get("knowledge_base", {})
        kb_lines = []
        if kb.get("people"):
            for name, info in list(kb["people"].items())[:10]:
                kb_lines.append(f"  [{name}]: {info}")
        if kb.get("rules"):
            for rule in kb["rules"][-5:]:
                kb_lines.append(f"  [规则] {rule}")
        if kb.get("lessons"):
            for lesson in kb["lessons"][-5:]:
                kb_lines.append(f"  [教训] {lesson}")
        if kb_lines:
            context_parts.append("[永久知识库]\n" + "\n".join(kb_lines))

        # Layer 1: Daily summaries (older context, last 7 days)
        daily = memory.get("daily_summaries", {})
        if daily:
            today = time.strftime("%m/%d")
            recent_days = sorted(daily.keys())[-7:]  # Last 7 days
            day_lines = []
            for day in recent_days:
                if day == today:
                    continue  # Today's details are in history already
                info = daily[day]
                topics = "、".join(info["topics"][:5])
                day_lines.append(f"  {day}: 聊了{info['count']}条 — {topics}")
            if day_lines:
                context_parts.append("[过去几天的对话摘要]\n" + "\n".join(day_lines))

        # Layer 2: Recent detailed history (last 20 messages)
        history = memory.get("history", [])
        if history:
            recent = "\n".join(history[-20:])
            context_parts.append(f"[最近对话记录]\n{recent}")

        # Combine context with current message
        if context_parts:
            context = "\n\n".join(context_parts)
            prompt = f"{context}\n\n[当前消息]\n{prompt}"

    # Select max_turns based on model complexity
    if model == "haiku":
        max_turns = MAX_TURNS_HAIKU
    elif model == "opus":
        max_turns = MAX_TURNS_OPUS
    else:
        max_turns = MAX_TURNS_SONNET

    # Build command — use claude.exe directly (compiled binary since v2.1+)
    cmd = [CLAUDE_EXE]
    if continue_session:
        cmd.append("-c")
    cmd += [
        "-p", prompt,
        "--output-format", "text",
        "--model", model,
        "--max-turns", str(max_turns),
        "--dangerously-skip-permissions",
        "--append-system-prompt", system_prompt,
    ]

    log(f"Running: claude -p (model={model} [{reason}], max_turns={max_turns}, cwd={cwd})")

    # Remove env vars that interfere with claude.exe auth
    # CLAUDECODE: avoid "nested session" error
    # CLAUDE_CODE_OAUTH_TOKEN: use credentials.json (auto-refreshed) instead of stale static token
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)

    def _is_prompt_too_long(text):
        """Check if text contains prompt-too-long indicators."""
        keywords = ["prompt is too long", "prompt too long",
                     "context length exceeded", "too many tokens", "context window"]
        return any(kw.lower() in text.lower() for kw in keywords)

    def _retry_without_session(fresh_cmd, cwd, env):
        """Retry command without -c flag (fresh session)."""
        try:
            fr = subprocess.run(fresh_cmd, cwd=cwd,
                                stdin=subprocess.DEVNULL,
                                capture_output=True,
                                text=True, timeout=CLAUDE_TIMEOUT,
                                encoding="utf-8", errors="replace",
                                shell=False, env=env)
            if fr.stdout.strip():
                return fr.stdout.strip()
        except Exception as fe:
            log(f"Fresh retry failed: {fe}")
        return None

    # Retry logic: up to 3 attempts for empty/failed/401 results
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            t_start = time.time()
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                env=env
            )
            # Store proc reference so /cancel can kill it
            global _current_proc
            with _current_proc_lock:
                _current_proc = proc

            try:
                # Poll-based wait with progress updates (every 60s)
                while True:
                    try:
                        raw_out, raw_err = proc.communicate(timeout=60)
                        break  # Completed
                    except subprocess.TimeoutExpired:
                        elapsed_so_far = time.time() - t_start
                        if elapsed_so_far >= CLAUDE_TIMEOUT:
                            proc.kill()
                            raw_out, raw_err = proc.communicate()
                            partial = (raw_out or "").strip()
                            if partial:
                                return (f"⏰ 超时了（{CLAUDE_TIMEOUT//60}分钟），但有部分结果：\n\n{partial}\n\n"
                                        f"（任务可能未完成，发消息给我继续）")
                            return f"老板，执行超时了（{CLAUDE_TIMEOUT//60}分钟），这个任务太复杂。要不要我把它拆小来做？"
                        # Progress update every 60s
                        mins = int(elapsed_so_far) // 60
                        log(f"Claude still running... {mins}m elapsed")
                        continue  # Keep waiting
            finally:
                with _current_proc_lock:
                    _current_proc = None

            elapsed = time.time() - t_start
            output = (raw_out or "").strip()
            stderr = (raw_err or "").strip()
            returncode = proc.returncode

            # Log diagnostics
            log(f"Claude CLI done: exit={returncode}, "
                f"stdout={len(output)}ch, stderr={len(stderr)}ch, "
                f"time={elapsed:.1f}s (attempt {attempt}/{max_retries})")

            # Cancelled by user
            if returncode == -9 or returncode == -15 or returncode == 1 and not output and not stderr:
                # Check if cancelled via /cancel
                if hasattr(proc, '_cancelled'):
                    return "✋ 任务已取消"

            # Detect transient network failure (DNS/connection/timeout) — distinct from auth
            combined = output + " " + stderr
            combined_lower = combined.lower()
            network_keywords = ["enotfound", "econnreset", "econnrefused", "etimedout",
                                "getaddrinfo", "fetch failed", "socket hang up",
                                "network is unreachable", "connection reset"]
            is_network = any(kw in combined_lower for kw in network_keywords)

            # Detect 401 auth error (only if NOT a network error)
            is_auth = (not is_network) and (
                "authentication_error" in combined_lower or
                ("401" in combined and "authenticate" in combined_lower)
            )

            if is_network:
                if attempt < max_retries:
                    wait = min(10 * attempt, 30)
                    log(f"🌐 Network error detected (attempt {attempt}/{max_retries}), retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                else:
                    log("❌ Network error persists — returning error to user (NOT restarting)")
                    return "🌐 老板，网络连不上 Claude 服务器，等一下再试试？（不是代码问题，等网络恢复）"

            if is_auth:
                if attempt < max_retries:
                    wait = 5 * attempt  # 5s, 10s backoff
                    log(f"🔑 Auth 401 detected (attempt {attempt}/{max_retries}), retrying in {wait}s...")
                    time.sleep(wait)
                    continue  # retry — claude.exe handles token refresh internally
                else:
                    # Don't restart bot (causes spam loop). Just inform user once with cooldown.
                    log("❌ Auth 401 persists after all retries — informing user (NOT restarting)")
                    global _last_auth_warn_ts
                    now = time.time()
                    if now - _last_auth_warn_ts > 600:  # only warn once per 10 min
                        _last_auth_warn_ts = now
                        return "🔑 老板，Claude API 认证有问题，可能 token 需要刷新。请检查 Claude CLI 登录状态（claude /login）"
                    return "🔑 API 认证还是不行，等会再试"

            if output:
                # Detect max turns hit
                if "Reached max turns" in output or "max turns" in output.lower():
                    return "⚠️ 老板，这次任务的操作步骤太多达到上限了。发条消息给我继续吧，我会接着做～"
                # Detect prompt too long
                if _is_prompt_too_long(output) and continue_session:
                    log("Prompt too long detected, retrying without -c...")
                    fresh_cmd = [x for x in cmd if x != "-c"]
                    result = _retry_without_session(fresh_cmd, cwd, env)
                    return result or "对话记录太长了，已尝试重置但失败，请发送 /new 开始新对话"
                return output

            # No stdout — check stderr for clues
            if stderr:
                if _is_prompt_too_long(stderr) and continue_session:
                    log(f"Prompt too long detected in stderr, retrying without -c: {stderr[:200]}")
                    fresh_cmd = [x for x in cmd if x != "-c"]
                    result = _retry_without_session(fresh_cmd, cwd, env)
                    return result or "对话记录太长了，已尝试重置但失败，请发送 /new 开始新对话"
                # If it's a transient error and we can retry
                transient_keywords = ["ECONNRESET", "ETIMEDOUT", "ENOTFOUND",
                                      "socket hang up", "network", "fetch failed",
                                      "rate limit", "529", "overloaded"]
                is_transient = any(kw.lower() in stderr.lower() for kw in transient_keywords)
                if is_transient and attempt < max_retries:
                    log(f"Transient error detected, retrying in 10s: {stderr[:200]}")
                    time.sleep(10)
                    continue
                return f"执行时遇到问题：{stderr[:500]}"

            # Both empty — very short run likely means CLI crashed or was killed
            if elapsed < 5:
                if attempt < max_retries:
                    log(f"CLI returned empty in {elapsed:.1f}s, retrying in 5s...")
                    time.sleep(5)
                    continue
                return "CLI 启动异常（秒退无输出），可能是网络或配置问题。"

            # Ran for a while but no output — API issue
            if attempt < max_retries:
                log(f"No output after {elapsed:.1f}s, retrying in 10s...")
                time.sleep(10)
                continue
            return f"（没有输出，运行了{elapsed:.0f}秒，退出码{returncode}）"

        except FileNotFoundError:
            return "老板，我找不到 claude 命令。请确保 Claude Code CLI 已安装。"
        except Exception as e:
            if attempt < max_retries:
                log(f"run_claude error (attempt {attempt}): {e}, retrying...")
                time.sleep(5)
                continue
            return f"执行出错了：{str(e)[:200]}"

    return "（重试后仍无输出）"


# ─── Command Handling ────────────────────────────────────────────
def handle_command(text, memory):
    """Handle special /commands. Returns (response, should_save_memory)."""
    if text == "/new":
        # Signal worker to reset session continuity
        _task_queue.put({'action': 'reset'})
        return "好的老板，新对话开始了 🆕 有什么吩咐？", False

    if text == "/status":
        m = memory.get("current_model", DEFAULT_MODEL)
        c = memory.get("cwd", DEFAULT_CWD)
        tasks = memory.get("tasks", [])
        pending = [t for t in tasks if t.get("status") != "done"]
        history_count = len(memory.get("history", []))
        return (
            f"📊 当前状态\n"
            f"工作目录：{c}\n"
            f"模型：{m}\n"
            f"待办任务：{len(pending)} 个\n"
            f"对话记忆：{history_count} 条\n"
            f"语音支持：{'✅' if VOICE_ENABLED else '❌'}"
        ), False

    if text == "/tasks":
        tasks = memory.get("tasks", [])
        if not tasks:
            return "📋 没有待办任务，很清闲呢～", False
        lines = ["📋 任务列表："]
        for i, t in enumerate(tasks, 1):
            status = "✅" if t.get("status") == "done" else "⏳"
            lines.append(f"{status} {i}. {t.get('desc', '?')}")
        return "\n".join(lines), False

    if text.startswith("/cd "):
        new_dir = text[4:].strip()
        # Support relative paths from current cwd
        if not os.path.isabs(new_dir):
            base = memory.get("cwd", DEFAULT_CWD)
            new_dir = os.path.normpath(os.path.join(base, new_dir))
        if os.path.isdir(new_dir):
            memory["cwd"] = new_dir
            return f"📁 工作目录已切换到：{new_dir}", True
        return f"❌ 目录不存在：{new_dir}", False

    if text.startswith("/model "):
        model = text[7:].strip().lower()
        if model == "auto":
            memory["manual_model"] = False
            memory["current_model"] = DEFAULT_MODEL
            return "🧠 已切换到自动模式，秘书会根据任务自动选择模型", True
        if model in ("opus", "sonnet", "haiku"):
            memory["current_model"] = model
            memory["manual_model"] = True
            return f"🧠 模型已锁定为 {model}（说「用auto」可恢复自动选择）", True
        return "❌ 可选模型：opus / sonnet / haiku / auto", False

    if text == "/stop":
        return "__STOP__", False

    if text == "/cancel":
        with _current_proc_lock:
            proc = _current_proc
        if proc and proc.poll() is None:
            proc._cancelled = True
            proc.kill()
            return "✋ 正在取消当前任务...", False
        return "没有正在运行的任务", False

    if text.startswith("/recall "):
        keyword = text[8:].strip()
        if not keyword:
            return "用法：/recall 关键词（搜索对话记忆）", False
        history = memory.get("history", [])
        daily = memory.get("daily_summaries", {})
        matches = []
        # Search recent history
        for h in history:
            if keyword.lower() in h.lower():
                matches.append(h)
        # Search daily summaries
        for day, info in sorted(daily.items()):
            for topic in info.get("topics", []):
                if keyword.lower() in topic.lower():
                    matches.append(f"[{day}] {topic}")
        if not matches:
            return f"找不到关于「{keyword}」的记忆", False
        result = f"🔍 搜索「{keyword}」找到 {len(matches)} 条：\n\n"
        for m in matches[-10:]:  # Show last 10 matches
            result += f"- {m[:120]}\n"
        return result, False

    if text in ("/health", "/ping"):
        import platform
        uptime_sec = time.time() - _bot_start_time
        h, rem = divmod(int(uptime_sec), 3600)
        m, s = divmod(rem, 60)
        uptime_str = f"{h}h{m}m{s}s" if h else f"{m}m{s}s"
        q_size = _task_queue.qsize()
        history_count = len(memory.get("history", []))
        model = memory.get("current_model", DEFAULT_MODEL)
        # Token usage stats
        usage = memory.get("token_usage", {})
        today_str = time.strftime("%Y-%m-%d")
        today_calls = usage.get(today_str, {}).get("calls", 0)
        today_secs = usage.get(today_str, {}).get("total_seconds", 0)
        # Worker status
        worker_alive = _worker_thread is not None and _worker_thread.is_alive()
        worker_status = "🟢 正常" if worker_alive else "🔴 已停止"
        return (
            f"🏥 小花健康报告\n"
            f"状态：🟢 运行中\n"
            f"运行时间���{uptime_str}\n"
            f"Python：{platform.python_version()}\n"
            f"Worker：{worker_status}\n"
            f"队列待处理：{q_size}\n"
            f"当前模型：{model}\n"
            f"记忆条数：{history_count}\n"
            f"今日调用：{today_calls} 次，{today_secs:.0f} 秒\n"
            f"语音���{'✅' if VOICE_ENABLED else '❌'}\n"
            f"Supabase：{'✅' if SUPABASE_SERVICE_KEY else '❌ 未配置'}\n"
            f"Groq：{'✅' if GROQ_API_KEY else '❌ 未配置'}"
        ), False

    if text == "/diagnose":
        send_msg("🔍 正在运行自我诊断，稍等...")
        report = run_diagnose()
        return report, False

    return None, False  # Not a command


def parse_cmd_tags(response, memory):
    """Parse [CMD:...] and [FILE:...] tags from Claude's response."""
    changed = False
    new_session = False

    # Parse [FILE:path] tags — send files to user
    file_matches = re.findall(r'\[FILE:(.*?)\]', response)
    for fpath in file_matches:
        fpath = fpath.strip()
        if os.path.isfile(fpath):
            ext = os.path.splitext(fpath)[1].lower()
            if ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
                send_photo(fpath)
            else:
                send_file(fpath)
        else:
            log(f"[FILE:] path not found: {fpath}")
    response = re.sub(r'\[FILE:.*?\]', '', response).strip()

    # Parse [CMD:action arg] tags
    cmd_match = re.search(r'\[CMD:(\w+)\s*(.*?)\]', response)
    if cmd_match:
        action = cmd_match.group(1).lower()
        arg = cmd_match.group(2).strip()
        # Remove tag from visible response
        response = re.sub(r'\[CMD:.*?\]', '', response).strip()
        # Execute the command
        if action == "cd" and arg:
            result, saved = handle_command(f"/cd {arg}", memory)
            if saved:
                changed = True
                log(f"Auto-executed: /cd {arg}")
        elif action == "model" and arg:
            result, saved = handle_command(f"/model {arg}", memory)
            if saved:
                changed = True
                log(f"Auto-executed: /model {arg}")
        elif action == "new":
            new_session = True
            log("Auto-executed: /new")

    if changed:
        save_memory(memory)
    return response, new_session


# ─── Main Loop ───────────────────────────────────────────────────
LOG_FILE = SCRIPT_DIR / "bot.log"


def log(msg):
    """Print log to console and append to bot.log file."""
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _track_usage(memory, elapsed_sec):
    """Track daily Claude CLI usage in memory for /health report."""
    today = time.strftime("%Y-%m-%d")
    usage = memory.setdefault("token_usage", {})
    if today not in usage:
        usage[today] = {"calls": 0, "total_seconds": 0}
    usage[today]["calls"] += 1
    usage[today]["total_seconds"] += elapsed_sec
    # Keep only last 7 days of usage data
    for key in list(usage.keys()):
        if key < (datetime.now().strftime("%Y-%m-%d")[:8] + "01"):  # roughly >30 days
            pass  # fine-grained cleanup below
    cutoff_keys = sorted(usage.keys())
    if len(cutoff_keys) > 7:
        for old_key in cutoff_keys[:-7]:
            del usage[old_key]


def task_worker(memory, typing_indicator):
    """Process tasks from queue sequentially, maintaining Claude session continuity.
    Runs in a dedicated thread so main loop stays responsive to new messages.
    """
    continue_session = False
    current_code = "?"
    while True:
        task = None
        reply_chat_id = CHAT_ID
        try:
            task = _task_queue.get()
            if task is None:  # shutdown sentinel
                break
            # Reset session signal from /new command
            if task.get('action') == 'reset':
                continue_session = False
                log("Session reset by /new")
                _task_queue.task_done()
                continue

            current_code = task['code']
            text = task['text']
            reply_chat_id = task.get('chat_id', CHAT_ID)

            memory["current_task"] = {
                "status": "processing",
                "code": current_code,
                "user_msg": text[:200],
                "timestamp": time.strftime("%m/%d %H:%M")
            }
            save_memory(memory)

            t_task_start = time.time()
            typing_indicator.start(chat_id=reply_chat_id)
            try:
                response = run_claude(text, memory, continue_session)
            finally:
                typing_indicator.stop()
            task_elapsed = time.time() - t_task_start

            # Track usage
            _track_usage(memory, task_elapsed)

            # 检查是否达到 max turns — 下次需要 continue session
            hit_max_turns = "操作步骤太多达到上限" in response
            if hit_max_turns:
                # 下次"继续"时用 -c 延续 Claude 会话，不从头来
                continue_session = True
            else:
                # 正常完成 → 重置 session，省 token
                continue_session = False
            memory["current_task"] = {"status": "done"}

            response, reset_session = parse_cmd_tags(response, memory)
            if reset_session:
                continue_session = False

            add_history(memory, text, response)
            save_memory(memory)

            send_msg(f"[{current_code}] {response}", chat_id=reply_chat_id)
            log(f"[{current_code}] Responded ({len(response)} chars, {task_elapsed:.0f}s) to {reply_chat_id}")

        except Exception as e:
            log(f"Task worker [{current_code}] error: {e}")
            log(traceback.format_exc())
            try:
                send_msg(f"[{current_code}] 出错了: {str(e)[:200]}", chat_id=reply_chat_id)
            except Exception:
                pass
        finally:
            try:
                _task_queue.task_done()
            except Exception:
                pass


_PIDFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secretary.pid")

def _pid_running(pid):
    """Check if a PID is alive AND is actually a python/secretary process."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=5
        )
        # Must be a python process, not some random reused PID
        return str(pid) in result.stdout and "python" in result.stdout.lower()
    except Exception:
        return False

def _acquire_lock():
    if os.path.exists(_PIDFILE):
        try:
            old_pid = int(open(_PIDFILE).read().strip())
            if old_pid != os.getpid() and _pid_running(old_pid):
                print(f"[LOCK] Another secretary instance already running (PID {old_pid}). Exiting.")
                sys.exit(99)  # 99 = duplicate instance, bat file should stop loop
            else:
                # Stale PID file — old process died, clean up
                os.remove(_PIDFILE)
        except (ValueError, IOError):
            pass
    with open(_PIDFILE, 'w') as f:
        f.write(str(os.getpid()))
    # Register cleanup on exit
    import atexit
    atexit.register(_release_lock)

def _release_lock():
    try:
        if os.path.exists(_PIDFILE):
            if int(open(_PIDFILE).read().strip()) == os.getpid():
                os.remove(_PIDFILE)
    except Exception:
        pass


def _trim_log_file():
    """Keep bot.log under 500KB by trimming old entries."""
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 500_000:
            lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
            # Keep last 2000 lines
            LOG_FILE.write_text("\n".join(lines[-2000:]) + "\n", encoding="utf-8")
    except Exception:
        pass


_bot_start_time = time.time()  # For /health uptime calculation


def main():
    global _bot_start_time
    _bot_start_time = time.time()
    _acquire_lock()
    _trim_log_file()
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set!")
        print("Set it as an environment variable or in .env file.")
        sys.exit(1)
    if not CHAT_ID:
        print("ERROR: TELEGRAM_CHAT_ID not set!")
        sys.exit(1)

    log("=" * 50)
    log("Telegram AI Secretary starting...")
    log(f"Bot Token: ...{BOT_TOKEN[-6:]}")
    log(f"Chat ID: {CHAT_ID}")
    log(f"Voice support: {'ENABLED' if VOICE_ENABLED else 'DISABLED'}")
    log(f"FFmpeg: {FFMPEG_PATH}")
    log("=" * 50)

    # ── Self-heal: check for previous crash and attempt auto-fix ──
    try:
        self_heal()
    except Exception as e:
        log(f"Self-heal itself failed: {e}")
        # Don't let self-heal failure prevent bot from starting

    memory = load_memory()
    _clean_history_errors(memory)  # Remove 401/error garbage from history
    # Expose memory globally so daily_reporter_thread can access it for self-review
    import __main__
    __main__._global_memory = memory
    log(f"Working directory: {memory.get('cwd', DEFAULT_CWD)}")
    log(f"Model: {memory.get('current_model', DEFAULT_MODEL)}")
    log(f"History entries: {len(memory.get('history', []))}")
    log(f"Knowledge base: {len(memory.get('knowledge_base', {}).get('lessons', []))} lessons, "
        f"{len(memory.get('knowledge_base', {}).get('people', {}))} people")

    # Startup throttle: suppress startup messages if restarting too frequently
    _startup_marker = SCRIPT_DIR / "_last_startup.txt"
    _suppress_startup_msg = False
    try:
        if _startup_marker.exists():
            last_start = float(_startup_marker.read_text().strip())
            if time.time() - last_start < 60:  # restarted within 60s = crash loop
                _suppress_startup_msg = True
                log("⚠️ Rapid restart detected, suppressing startup message")
        _startup_marker.write_text(str(time.time()))
    except Exception:
        pass

    # Check for interrupted task from previous crash
    interrupted = memory.get("current_task")
    if interrupted and interrupted.get("status") == "processing":
        task_msg = interrupted.get("user_msg", "")
        task_time = interrupted.get("timestamp", "")
        log(f"Found interrupted task: {task_msg[:60]}...")
        if not _suppress_startup_msg:
            restart_text = "秘书重新上线了!\n\n上次掉线前正在处理你的指令:\n" + task_msg[:100] + "\n\n需要我继续处理吗? 回复 继续 我就接着做"
            send_msg(restart_text)
        # Clear the interrupted task so we don't ask again on next restart
        memory["current_task"] = {"status": "interrupted_notified", "user_msg": task_msg}
        save_memory(memory)
    else:
        # Normal startup
        if not _suppress_startup_msg:
            voice_status = "🎤 语音已启用" if VOICE_ENABLED else "⌨️ 仅文字模式"
            send_msg(f"🟢 秘书上线了！{voice_status}\n有什么吩咐随时说～")

    # Start daily reporter background thread (10:00 & 22:00)
    reporter = threading.Thread(target=daily_reporter_thread, daemon=True)
    reporter.start()
    log("Daily reporter started — will send at 10:00 & 22:00 daily")

    # Clean old received files on startup (>7 days)
    _clean_received_files()

    # Auto backup memory on startup
    try:
        import importlib.util
        backup_script = SCRIPT_DIR / "backup_memory.py"
        if backup_script.exists():
            spec = importlib.util.spec_from_file_location("backup_memory", backup_script)
            bm = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(bm)
            bm.backup_memory()
            log("Memory backup completed on startup")
    except Exception as e:
        log(f"Memory backup failed (non-critical): {e}")

    typing = TypingIndicator()

    # Start task worker thread — processes messages sequentially while main loop stays responsive
    global _worker_thread
    worker = threading.Thread(target=task_worker, args=(memory, typing), daemon=True, name="task_worker")
    worker.start()
    _worker_thread = worker
    log("Task worker started — main loop will dispatch messages to queue")

    offset = memory.get("telegram_offset", 0)
    if offset:
        log(f"Resuming from saved offset: {offset}")
    consecutive_errors = 0
    last_outage_log_ts = 0  # rate-limit outage logging

    while True:
        try:
            # Long poll for updates
            resp = tg_api("getUpdates", {
                "offset": offset,
                "timeout": 30
            })

            if not resp.get("ok"):
                consecutive_errors += 1
                # Exponential backoff: 5 → 15 → 30 → 60s (cap)
                if consecutive_errors <= 1:
                    backoff = 5
                elif consecutive_errors <= 3:
                    backoff = 15
                elif consecutive_errors <= 6:
                    backoff = 30
                else:
                    backoff = 60
                # Rate-limit logging during long outages: log every 5 min
                now = time.time()
                if consecutive_errors <= 3 or (now - last_outage_log_ts) > 300:
                    log(f"getUpdates failed (#{consecutive_errors}, backoff={backoff}s): {resp.get('error', '?')}")
                    last_outage_log_ts = now
                # On long outage (>10 consecutive failures over ~5min), notify boss once
                global _last_network_warn_ts
                if consecutive_errors == 10 and (now - _last_network_warn_ts) > 1800:
                    _last_network_warn_ts = now
                    try:
                        send_msg("🌐 老板，网络好像断了，我会一直重试，等网络恢复就回来 👍")
                    except Exception:
                        pass
                time.sleep(backoff)
                continue

            # Successful response — reset error counter
            if consecutive_errors > 0:
                if consecutive_errors >= 3:
                    log(f"✅ Network recovered after {consecutive_errors} failures")
                    try:
                        send_msg("✅ 网络恢复了，小花重新上线 🎉")
                    except Exception:
                        pass
                consecutive_errors = 0

            for update in resp.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "").strip()
                caption = msg.get("caption", "").strip()

                # Security: only respond to configured chat ID or boss commands in GCFB group
                sender_id = str(msg.get("from", {}).get("id", ""))
                if chat_id != CHAT_ID:
                    if GCFB_GROUP_CHAT_ID and chat_id == GCFB_GROUP_CHAT_ID:
                        # 只处理老大发的群消息，小花和小虾自动分工
                        is_boss = sender_id == BOSS_USER_ID
                        if is_boss:
                            combined_text = (text + " " + caption).lower()
                            # 如果老大明确叫小虾（@Gcfbai_openclaw_bot）而没有叫小花 → 小花不插话
                            calls_xiaoxia_only = (
                                ("gcfbai_openclaw_bot" in combined_text or "小虾" in combined_text)
                                and "小花" not in combined_text
                                and "gcfbboss_bot" not in combined_text
                            )
                            if calls_xiaoxia_only:
                                log(f"Group msg for 小虾 only, 小花 silent: {text[:50]}")
                                continue
                            # ── 方案1：独立会话通道 ──
                            # 群消息转到私聊处理，不在群里刷屏
                            # 只有明确叫小花的消息才处理
                            calls_xiaohua = (
                                "小花" in combined_text
                                or "gcfbboss_bot" in combined_text
                            )
                            if not calls_xiaohua:
                                # 老大没有指名叫小花，不处理（避免抢小虾的活或无关消息）
                                log(f"Group msg not for 小花, skipping: {text[:50]}")
                                continue
                            # 群里回复（不转私聊，让群成员也看到）
                            log(f"Group msg from boss for 小花: {text[:50]}")
                        else:
                            log(f"Ignored non-boss message in GCFB group (sender: {sender_id})")
                            continue
                    else:
                        log(f"Ignored message from unknown chat: {chat_id}")
                        continue

                # ── Handle voice message ──
                voice = msg.get("voice")
                if voice and not text:
                    file_id = voice.get("file_id")
                    if file_id:
                        if not VOICE_ENABLED:
                            send_msg("语音功能未启用，请安装 SpeechRecognition 和 pydub")
                            continue
                        ogg_path = download_voice(file_id)
                        if ogg_path:
                            text = transcribe_voice(ogg_path)
                            if not text:
                                send_msg("抱歉老板，没听清楚，能再说一次吗？ 🙉")
                                continue
                        else:
                            send_msg("语音下载失败了，请重新发送")
                            continue

                # ── Handle photo ──
                photo = msg.get("photo")
                if photo:
                    # Telegram sends multiple sizes, take largest
                    file_id = photo[-1]["file_id"]
                    path = download_telegram_file(file_id, suffix=".jpg")
                    if path:
                        user_caption = text or caption or ""
                        text = user_caption + f"\n[用户发了一张图片，已保存在: {path}。请务必用 Read 工具读取这个图片文件，看清楚图片内容后再回答。]"

                # ── Handle document/file ──
                doc = msg.get("document")
                if doc:
                    file_name = doc.get("file_name", "file")
                    file_id = doc["file_id"]
                    path = download_telegram_file(file_id, filename=file_name)
                    if path:
                        text = (text or caption or "") + f"\n[用户发了文件 {file_name}，已保存在: {path}]"

                if not text:
                    continue

                text = text.strip()
                log(f"Received: {text[:80]}...")

                # Handle special commands (still support /commands as fallback)
                cmd_response, should_save = handle_command(text, memory)
                if cmd_response == "__STOP__":
                    send_msg("🔴 秘书下线了，再见老板！")
                    log("Stopped by /stop command")
                    save_memory(memory)
                    return
                if cmd_response is not None:
                    send_msg(cmd_response)
                    if should_save:
                        save_memory(memory)
                    continue

                # Normal message → enqueue for background processing
                # Main loop stays responsive; worker sends result with task code
                code = _next_task_code()
                q_size = _task_queue.qsize()
                queue_note = f"（前面还有 {q_size} 个任务排队）" if q_size > 0 else ""
                send_msg(f"[{code}] 收到，处理中...{queue_note}", chat_id=chat_id)
                _task_queue.put({'code': code, 'text': text, 'chat_id': chat_id})
                log(f"[{code}] Queued (pos={q_size+1}): {text[:60]}")
                consecutive_errors = 0

                # Watchdog: restart worker if it died
                if _worker_thread and not _worker_thread.is_alive():
                    log("⚠️ Worker thread died! Restarting...")
                    _worker_thread = threading.Thread(
                        target=task_worker, args=(memory, typing), daemon=True, name="task_worker"
                    )
                    _worker_thread.start()
                    log("✅ Worker thread restarted")

            # Persist offset after processing batch (prevents duplicate processing on restart)
            if resp.get("result") and offset != memory.get("telegram_offset", 0):
                memory["telegram_offset"] = offset
                save_memory(memory)

        except KeyboardInterrupt:
            log("Shutting down (Ctrl+C)")
            send_msg("🔴 秘书下线了")
            save_memory(memory)
            _release_lock()
            break
        except Exception as e:
            consecutive_errors += 1
            log(f"Error in main loop ({consecutive_errors}x): {e}")
            log_error_to_disk(e)

            if consecutive_errors >= CONSECUTIVE_ERROR_LIMIT:
                # Safe mode: notify user + long pause
                log(f"Safe mode triggered after {consecutive_errors} consecutive errors")
                try:
                    send_msg(
                        f"老板，我连续出错{consecutive_errors}次了，"
                        f"暂停60秒观察一下...\n"
                        f"最新错误: {str(e)[:200]}"
                    )
                except Exception:
                    pass
                time.sleep(60)
                consecutive_errors = 0
            else:
                time.sleep(5)


# ─── Daily Auto Report ───────────────────────────────────────────
def _take_screenshot():
    """Take a screenshot and return the saved path."""
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-File", SS_SCRIPT],
            timeout=10, capture_output=True
        )
        return SS_PATH
    except Exception as e:
        log(f"Screenshot failed: {e}")
        return None



def send_booking_report_5pm():
    """每天 17:00 发送今日预约汇报。"""
    import urllib.request as _urllib
    import json as _json

    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    log("Booking report 17:00 triggered")

    ctx = SSL_CTX  # Use global certifi-backed SSL context

    BOOK_API = f"https://script.google.com/macros/s/AKfycbyq1uhgRek_xCtOeAeWnS6mKxoYI4FMSiezAHlGHB-GXkJNGIZNTaotIT76CmKNvoY_/exec?page=api&key=zchhp2024&action={date_str}"

    try:
        req = _urllib.Request(BOOK_API, headers={"User-Agent": "Mozilla/5.0"})
        raw = _urllib.urlopen(req, context=ctx, timeout=20).read().decode()
        book = _json.loads(raw)
        bookings = book.get('bookings', [])
        total_b = book.get('total', len(bookings))

        lines = [f"📅 今日预约汇报 {date_str}  共 {total_b} 张"]
        if bookings:
            for b in bookings:
                status_icon = "✅" if b.get('status') == 'accepted' else ("❌" if b.get('status') == 'cancelled' else "⏳")
                lines.append(f"{status_icon} {b.get('time','?')}  {b.get('name','?')}  {b.get('pax','?')}人")
        else:
            lines.append("今日暂无预约")

        send_msg("\n".join(lines))
    except Exception as e:
        log(f"send_booking_report_5pm error: {e}")
        send_msg(f"⚠️ 预约汇报查询失败: {e}")


def send_pm2_report():
    """每天 9:00 检查所有 PM2 进程状态并汇报"""
    try:
        result = subprocess.run(
            "npx pm2 jlist",
            shell=True, capture_output=True, text=True, timeout=30,
            cwd=str(SCRIPT_DIR)
        )
        if result.returncode != 0 or not result.stdout.strip():
            send_msg(f"⚠️ PM2 检查失败\n{result.stderr[:150]}")
            return

        import json as _pj
        try:
            processes = _pj.loads(result.stdout)
        except Exception:
            send_msg(f"⚠️ PM2 输出解析失败：{result.stdout[:200]}")
            return

        if not processes:
            send_msg("🔴 PM2 目前没有任何进程")
            return

        lines = [f"🤖 PM2 状态 09:00  {datetime.now().strftime('%Y-%m-%d')}"]
        all_ok = True
        for p in processes:
            name = p.get('name', '?')
            env = p.get('pm2_env', {})
            status = env.get('status', '?')
            restarts = env.get('restart_time', 0)
            mem_bytes = (p.get('monit') or {}).get('memory', 0)
            mem_mb = round(mem_bytes / 1024 / 1024, 1)

            icon = '✅' if status == 'online' else '❌'
            if status != 'online':
                all_ok = False

            restart_note = ''
            if restarts > 10:
                restart_note = f'  ⚠️重启{restarts}次'
            elif restarts > 0:
                restart_note = f'  (重启{restarts}次)'

            lines.append(f"{icon} {name}  {status}  {mem_mb}MB{restart_note}")

        lines.append('')
        lines.append('全部正常 👍' if all_ok else '⚠️ 有进程不正常，请检查！')
        send_msg('\n'.join(lines))
        log("PM2 status report sent at 09:00")
    except Exception as e:
        send_msg(f"❌ PM2 检查出错：{str(e)[:100]}")
        log(f"PM2 report error: {e}")


def send_daily_report():
    """Compose and send the daily report. Morning (10am) = booking + LDS brief. Evening (10pm) = full report."""
    import urllib.request as _urllib
    import json as _json

    now = datetime.now()
    is_morning = now.hour < 12
    period = "早上" if is_morning else "晚上"
    date_str = now.strftime('%Y-%m-%d')
    log(f"Daily report triggered at {now.strftime('%H:%M')}")
    send_msg(f"⏰ {period} {now.strftime('%H:%M')} 自动汇报来了，正在查数据...")

    ctx = SSL_CTX  # Use global certifi-backed SSL context

    LDS_API        = "https://script.google.com/macros/s/AKfycbzTxymBxmmliLWpOdg-lh-Ev6tDKyjEf91wgTaDAtxx0gtEsZZrsL9rL9AFv7-XaySlew/exec?page=api&key=zchhp2024"
    BOOK_API       = "https://script.google.com/macros/s/AKfycbyq1uhgRek_xCtOeAeWnS6mKxoYI4FMSiezAHlGHB-GXkJNGIZNTaotIT76CmKNvoY_/exec?page=api&key=zchhp2024"
    CHAT_STATS_API = "https://script.google.com/macros/s/AKfycbw45op0Bqn4E8iHIbVLdGi-cLWFt-rEiEooWzwiynd6zIv6WoR7X9vIShdzIjTAa-_v/exec?action=stats&key=zchhp2024"

    try:
        # ── Query Booking (both reports need it) ──
        req2 = _urllib.Request(BOOK_API, headers={"User-Agent": "Mozilla/5.0"})
        book = _json.loads(_urllib.urlopen(req2, context=ctx, timeout=20).read().decode())
        bookings = book.get('bookings', [])
        total_b  = book.get('total', len(bookings))
        pending  = book.get('pending', '?')
        accepted = book.get('accepted', '?')

        if is_morning:
            # ════ 早报 10am：今日预约列表 + 昨日LDS新用户 + 打印服务器状态 ════
            req = _urllib.Request(LDS_API, headers={"User-Agent": "Mozilla/5.0"})
            lds = _json.loads(_urllib.urlopen(req, context=ctx, timeout=20).read().decode())

            book_lines = [f"📅 今日预约 {date_str}  共 {total_b} 张"]
            if bookings:
                for b in bookings:
                    status_icon = "✅" if b.get('status') == 'accepted' else ("❌" if b.get('status') == 'cancelled' else "⏳")
                    line = f"{status_icon} {b.get('time','?')}  {b.get('name','?')}  {b.get('pax','?')}人"
                    book_lines.append(line)
            else:
                book_lines.append("今日暂无预约")

            # ── 打印服务器状态（9点已自动重启，检查是否正常）──
            try:
                import urllib.request as _ur2
                ps_req = _ur2.Request("http://localhost:3333/health", headers={"User-Agent": "Mozilla/5.0"})
                ps_resp = _json.loads(_ur2.urlopen(ps_req, timeout=5).read().decode())
                ps_ok = ps_resp.get('status') == 'ok'
                ps_connected = ps_resp.get('realtimeConnected', False)
                if ps_ok and ps_connected:
                    print_status = "✅ 打印服务器正常（9:00 已重启）"
                else:
                    print_status = f"⚠️ 打印服务器异常 status={ps_resp.get('status')} connected={ps_connected}"
            except Exception as _pe:
                print_status = f"❌ 打印服务器无响应 ({str(_pe)[:50]})"

            report = (
                f"🌅 早报 {date_str}\n\n"
                + "\n".join(book_lines)
                + f"\n\n🎰 昨日LDS新用户：{lds.get('todayNewUsers', '?')} 人  累计：{lds.get('totalUsers', '?')} 人"
                + f"\n\n🖨 {print_status}"
            )

        else:
            # ════ 晚报 10pm：LDS完整 + 预约汇总 + 小慧 + DocuScan ════
            req = _urllib.Request(LDS_API, headers={"User-Agent": "Mozilla/5.0"})
            lds = _json.loads(_urllib.urlopen(req, context=ctx, timeout=20).read().decode())

            # LDS section
            lds_lines = [
                "🎰 【抽奖系统 LDS】",
                f"今日新用户：{lds.get('todayNewUsers', '?')} 人  累计：{lds.get('totalUsers', '?')} 人",
                f"今日抽奖：{lds.get('todayDraws', '?')} 次  累计：{lds.get('totalDraws', '?')} 次",
                f"今日兑换：{lds.get('todayVerified', '?')} 张  累计已兑换：{lds.get('totalVerified', '?')} 张",
                f"待兑换：{lds.get('totalPending', '?')} 张",
            ]

            # Booking section
            book_lines = [
                f"📅 【预约系统】今日 {date_str} 共 {total_b} 张",
                f"待处理：{pending}  已接受：{accepted}",
            ]
            if bookings:
                for b in bookings:
                    status_icon = "✅" if b.get('status') == 'accepted' else ("❌" if b.get('status') == 'cancelled' else "⏳")
                    line = f"{status_icon} {b.get('time','?')}  {b.get('name','?')}  {b.get('pax','?')}人"
                    book_lines.append(line)
            else:
                book_lines.append("今日暂无预约")

            report = (
                f"📊 晚报 {date_str}\n\n"
                + "\n".join(lds_lines)
                + "\n\n"
                + "\n".join(book_lines)
            )

        send_msg(report)
        log("Daily report sent successfully via API")

    except Exception as e:
        log(f"Daily report error: {e}")
        send_msg(f"自动汇报出错了 😅\n{str(e)[:300]}")


def check_scheduled_tasks(now):
    """Check scheduled_tasks.json and send any due tasks."""
    tasks_file = SCRIPT_DIR / "scheduled_tasks.json"
    if not tasks_file.exists():
        return
    try:
        import json as _json
        with open(tasks_file, "r", encoding="utf-8") as f:
            tasks = _json.load(f)

        remaining = []
        for task in tasks:
            task_dt = datetime.strptime(task["datetime"], "%Y-%m-%d %H:%M")
            if now >= task_dt:
                # Send the task
                action = task.get("action", "")
                if action == "send_daily_report":
                    t = threading.Thread(target=send_daily_report, daemon=True)
                    t.start()
                elif "message_file" in task:
                    msg_path = SCRIPT_DIR / task["message_file"]
                    if msg_path.exists():
                        with open(msg_path, "r", encoding="utf-8") as mf:
                            content = mf.read()
                        # Split into chunks of 3000 chars to avoid Telegram limit
                        chunks = [content[i:i+3000] for i in range(0, len(content), 3000)]
                        for chunk in chunks:
                            send_msg(chunk)
                elif "message" in task:
                    send_msg(task["message"])
                log(f"Scheduled task sent: {task.get('label', task['datetime'])}")
            else:
                remaining.append(task)

        with open(tasks_file, "w", encoding="utf-8") as f:
            _json.dump(remaining, f, ensure_ascii=False, indent=2)

    except Exception as e:
        log(f"check_scheduled_tasks error: {e}")


def sync_ddfresh_prices():
    """每天 22:10 自动同步 DD Fresh 最新报价（DD Fresh 22:00 更新）"""
    try:
        import subprocess
        script = str(SCRIPT_DIR / "sync_supplier_prices.py")
        result = subprocess.run(
            ["python", script],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}
        )
        log(f"DD Fresh sync done: {result.stdout[-300:] if result.stdout else 'no output'}")
        if result.returncode != 0:
            log(f"DD Fresh sync error: {result.stderr[-200:]}")
    except Exception as e:
        log(f"DD Fresh sync exception: {e}")


def sync_ebuy_prices():
    """每天 22:20 自动同步 eBuy 最新报价"""
    try:
        import subprocess
        script = str(SCRIPT_DIR / "sync_ebuy_prices.py")
        result = subprocess.run(
            ["python", script],
            capture_output=True, text=True, timeout=180,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}
        )
        log(f"eBuy sync done: {result.stdout[-300:] if result.stdout else 'no output'}")
        if result.returncode != 0:
            log(f"eBuy sync error: {result.stderr[-200:]}")
    except Exception as e:
        log(f"eBuy sync exception: {e}")


# ─── Health Check System ─────────────────────────────────────────
HEALTH_STATE_FILE = SCRIPT_DIR / "health_state.json"

def load_health_state():
    """Load last health check status from disk."""
    if HEALTH_STATE_FILE.exists():
        try:
            with open(HEALTH_STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_health_state(state):
    """Save health check status to disk."""
    with open(HEALTH_STATE_FILE, 'w') as f:
        json.dump(state, f)

def check_system_health():
    """Check health of all critical systems, send alert if status changes."""
    health_state = load_health_state()

    # Define systems to monitor
    systems = {
        "POS System": "https://pos-system-hazel-psi.vercel.app/api/menu/categories",
        "Booking": "https://script.google.com/macros/s/AKfycbyq1uhgRek_xCtOeAeWnS6mKxoYI4FMSiezAHlGHB-GXkJNGIZNTaotIT76CmKNvoY_/exec?page=api&key=zchhp2024",
        "LDS": "https://script.google.com/macros/s/AKfycbzTxymBxmmliLWpOdg-lh-Ev6tDKyjEf91wgTaDAtxx0gtEsZZrsL9rL9AFv7-XaySlew/exec?page=api&key=zchhp2024",
    }

    alerts = []

    for system_name, url in systems.items():
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
                is_healthy = 200 <= resp.status < 400
        except:
            is_healthy = False

        # Check if status changed
        prev_status = health_state.get(system_name, True)  # default to healthy
        if is_healthy != prev_status:
            if is_healthy:
                alerts.append(f"✅ {system_name} 已恢复正常")
            else:
                alerts.append(f"⚠️ {system_name} 无法访问！")
            health_state[system_name] = is_healthy

    if alerts:
        send_msg("系统监控告警:\n" + "\n".join(alerts))

    save_health_state(health_state)


def nightly_self_review(memory):
    """23:30 自我学习：让 Claude 从今天的对话里提炼关键知识，存进 knowledge_base。"""
    history = memory.get("history", [])
    if not history:
        return

    # 取最近40条对话（当天为主）
    today = time.strftime("%m/%d")
    today_entries = [h for h in history if today in h]
    if len(today_entries) < 3:
        return  # 今天对话太少，不值得提炼

    entries_text = "\n".join(today_entries[-40:])
    prompt = f"""以下是今天的对话记录：

{entries_text}

请从这些对话中提炼出值得长期记住的知识。只提炼真正重要的内容，不要凑数。

请用 JSON 格式回复，只输出 JSON，不要其他文字：
{{
  "people": {{"姓名": "关键信息，如职位/薪资结构/特殊情况"}},
  "rules": ["重要业务规则或决策"],
  "lessons": ["值得记住的教训或最佳实践"]
}}

如果某类没有新内容，对应字段用空对象/空数组。"""

    try:
        result = run_claude(prompt, memory, continue_session=False)
        # 从结果里提取 JSON
        json_match = re.search(r'\{[\s\S]+\}', result)
        if not json_match:
            return
        extracted = json.loads(json_match.group())

        kb = memory.setdefault("knowledge_base", {
            "people": {}, "systems": {}, "rules": [], "lessons": []
        })

        # 更新 people
        for name, info in extracted.get("people", {}).items():
            if name and info:
                kb["people"][name] = info

        # 追加 rules（去重）
        for rule in extracted.get("rules", []):
            if rule and rule not in kb["rules"]:
                kb["rules"].append(rule)
        kb["rules"] = kb["rules"][-30:]

        # 追加 lessons（去重）
        for lesson in extracted.get("lessons", []):
            if lesson and lesson not in kb["lessons"]:
                kb["lessons"].append(lesson)
        kb["lessons"] = kb["lessons"][-30:]

        save_memory(memory)
        log(f"Nightly self-review done: {len(extracted.get('people',{}))} people, "
            f"{len(extracted.get('rules',[]))} rules, {len(extracted.get('lessons',[]))} lessons")
    except Exception as e:
        log(f"Nightly self-review error: {e}")


def check_pos_anomaly():
    """检查今日 POS 销售是否异常（vs 7天均值），如有大幅偏差则告警。"""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return

    try:
        # 查今天和过去7天的订单数/营业额
        today = time.strftime("%Y-%m-%d")
        url = f"{SUPABASE_URL}/rest/v1/pos_orders?select=total,closed_at&status=eq.closed&closed_at=gte.{today}T00:00:00"
        req = urllib.request.Request(url, headers={
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        })
        with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as r:
            today_orders = json.loads(r.read())

        if not today_orders:
            return

        today_count = len(today_orders)
        today_revenue = sum(float(o.get("total", 0) or 0) for o in today_orders)

        # 查过去7天
        from datetime import timedelta
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        url7 = f"{SUPABASE_URL}/rest/v1/pos_orders?select=total,closed_at&status=eq.closed&closed_at=gte.{week_ago}T00:00:00&closed_at=lt.{today}T00:00:00"
        req7 = urllib.request.Request(url7, headers={
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        })
        with urllib.request.urlopen(req7, timeout=15, context=SSL_CTX) as r:
            week_orders = json.loads(r.read())

        if not week_orders:
            return

        avg_daily_count = len(week_orders) / 7
        avg_daily_revenue = sum(float(o.get("total", 0) or 0) for o in week_orders) / 7

        alerts = []
        if avg_daily_count > 5 and today_count < avg_daily_count * 0.5:
            alerts.append(f"今日订单数 {today_count} 笔，比7天均值 {avg_daily_count:.0f} 少超过50%！")
        if avg_daily_revenue > 100 and today_revenue < avg_daily_revenue * 0.5:
            alerts.append(f"今日营业额 RM{today_revenue:.0f}，比7天均值 RM{avg_daily_revenue:.0f} 少超过50%！")

        if alerts:
            send_msg("⚠️ POS 异常检测：\n" + "\n".join(alerts))
            log(f"POS anomaly alert sent: {alerts}")

    except Exception as e:
        log(f"POS anomaly check error: {e}")


def daily_reporter_thread():
    """Background daemon thread: check time every minute, trigger scheduled tasks."""
    sent_keys = set()   # (date_str, label) pairs already sent today
    last_health_check = 0  # timestamp of last health check
    last_mailbox_check = 0  # timestamp of last mailbox check

    # Memory reference passed from main
    _memory_ref = [None]

    def get_mem():
        """Get memory from global memory variable."""
        try:
            import __main__
            return getattr(__main__, '_global_memory', None)
        except Exception:
            return None

    while True:
        try:
            now = datetime.now()

            # 每日定时汇报：10:00 & 22:00
            if now.hour in REPORT_HOURS and now.minute == 0:
                key = (now.strftime("%Y-%m-%d"), now.hour)
                if key not in sent_keys:
                    sent_keys.add(key)
                    t = threading.Thread(target=send_daily_report, daemon=True)
                    t.start()

            # PM2 状态检查：每天 9:00
            if now.hour == 9 and now.minute == 0:
                key = (now.strftime("%Y-%m-%d"), "pm2_check")
                if key not in sent_keys:
                    sent_keys.add(key)
                    t = threading.Thread(target=send_pm2_report, daemon=True)
                    t.start()
                    log("PM2 status check triggered at 09:00")

            # POS 异常检测：每天 14:00（午餐后检查午市数据）
            if now.hour == 14 and now.minute == 0:
                key = (now.strftime("%Y-%m-%d"), "pos_anomaly")
                if key not in sent_keys:
                    sent_keys.add(key)
                    t = threading.Thread(target=check_pos_anomaly, daemon=True)
                    t.start()
                    log("POS anomaly check triggered at 14:00")

            # 预约汇报：每天 17:00
            if now.hour == 17 and now.minute == 0:
                key = (now.strftime("%Y-%m-%d"), "booking_5pm")
                if key not in sent_keys:
                    sent_keys.add(key)
                    t = threading.Thread(target=send_booking_report_5pm, daemon=True)
                    t.start()
                    log("Booking report 17:00 triggered")

            # DD Fresh 价格同步：每天 22:10
            if now.hour == 22 and now.minute == 10:
                key = (now.strftime("%Y-%m-%d"), "ddfresh")
                if key not in sent_keys:
                    sent_keys.add(key)
                    t = threading.Thread(target=sync_ddfresh_prices, daemon=True)
                    t.start()
                    log("DD Fresh price sync started")

            # eBuy 价格同步：每天 22:20
            if now.hour == 22 and now.minute == 20:
                key = (now.strftime("%Y-%m-%d"), "ebuy")
                if key not in sent_keys:
                    sent_keys.add(key)
                    t = threading.Thread(target=sync_ebuy_prices, daemon=True)
                    t.start()
                    log("eBuy price sync started")

            # 夜间自我学习：每天 23:30（提炼今天对话关键知识）
            if now.hour == 23 and now.minute == 30:
                key = (now.strftime("%Y-%m-%d"), "self_review")
                if key not in sent_keys:
                    sent_keys.add(key)
                    mem = get_mem()
                    if mem is not None:
                        t = threading.Thread(
                            target=nightly_self_review, args=(mem,), daemon=True
                        )
                        t.start()
                        log("Nightly self-review triggered at 23:30")

            # Check scheduled one-off tasks
            check_scheduled_tasks(now)

            # 系统健康检查：每小时一次（整点），跳过 00:00-08:00 休息时段
            current_time = time.time()
            if now.minute == 0 and now.hour >= 8 and current_time - last_health_check >= 3600:
                try:
                    check_system_health()
                except Exception as e:
                    log(f"Health check error: {e}")
                last_health_check = current_time

            # 小虾留言检查：每小时一次
            if current_time - last_mailbox_check >= 3600:
                try:
                    check_xiaoxia_mailbox()
                except Exception as e:
                    log(f"Mailbox check error: {e}")
                last_mailbox_check = current_time

            # Clean up keys from previous days
            today = now.strftime("%Y-%m-%d")
            sent_keys = {k for k in sent_keys if k[0] == today}

        except Exception as e:
            log(f"Daily reporter loop error: {e}")

        time.sleep(60)


if __name__ == "__main__":
    main()
