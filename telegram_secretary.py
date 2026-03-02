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
import re
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

# SSL: use certifi CA bundle for proper certificate verification
import certifi
SSL_CTX = ssl.create_default_context(cafile=certifi.where())

# ─── Configuration ───────────────────────────────────────────────
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
GCFB_GROUP_CHAT_ID = os.environ.get("GCFB_GROUP_CHAT_ID", "")  # GCFB CUSTOMER SERVICE 群
BOSS_USER_ID = CHAT_ID  # 老板的 user_id 等于私聊 chat_id
SCRIPT_DIR = Path(__file__).parent
MEMORY_FILE = SCRIPT_DIR / "memory.json"
SYSTEM_PROMPT_FILE = SCRIPT_DIR / "system_prompt.txt"
CLAUDE_TIMEOUT = 600  # 10 minutes max per command
MAX_TURNS = 100
DEFAULT_MODEL = "sonnet"
DEFAULT_CWD = os.environ.get(
    "SECRETARY_CWD",
    str(Path.home() / "Documents" / "cluade code")
)
# Call node.exe + cli.js directly to bypass cmd.exe newline truncation bug
NODE_EXE = os.environ.get(
    "NODE_EXE",
    r"C:\Users\Admin23\nodejs\node.exe"
)
CLAUDE_CLI_JS = os.environ.get(
    "CLAUDE_CLI_JS",
    r"C:\Users\Admin23\nodejs\node_modules\@anthropic-ai\claude-code\cli.js"
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

# ─── Self-Heal Configuration ────────────────────────────────────
CRASH_LOG_FILE = SCRIPT_DIR / "crash_log.txt"
HEAL_STATE_FILE = SCRIPT_DIR / "heal_state.json"
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
            log(f"Telegram API error ({method}, attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(3)
            else:
                return {"ok": False, "error": str(e)}


def clean_response(text):
    """Remove internal context headers that may leak into Claude's response."""
    # Strip context headers that were injected into the prompt
    headers = [
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

    def start(self):
        self._running = True
        self._send_loop()

    def _send_loop(self):
        if self._running:
            tg_api("sendChatAction", {"chat_id": CHAT_ID, "action": "typing"})
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


def transcribe_voice(ogg_path):
    """Convert OGG voice to text. Tries Chinese first, then English."""
    if not VOICE_ENABLED:
        return None
    wav_path = ogg_path.replace(".ogg", ".wav")
    try:
        # Convert OGG → WAV using pydub + ffmpeg
        log("Converting OGG → WAV...")
        audio = AudioSegment.from_ogg(ogg_path)
        audio.export(wav_path, format="wav")
        log("WAV conversion done, starting recognition...")

        # Recognize speech — try Chinese first, then English
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)

        for lang in ["zh-CN", "en-US"]:
            text = _recognize_with_timeout(recognizer, audio_data, lang, timeout=30)
            if text:
                log(f"Voice recognized ({lang}): {text[:60]}...")
                return text
        log("Voice not recognized in any language")
        return None
    except Exception as e:
        log(f"Transcription error: {e}")
        return None
    finally:
        # Cleanup temp files
        for f in [ogg_path, wav_path]:
            try:
                os.unlink(f)
            except Exception:
                pass


# ─── Self-Heal System ────────────────────────────────────────────
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
    HEAL_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def get_error_signature(stderr_text):
    """Generate a normalized signature for an error to track unique errors.
    Strips line numbers, timestamps, and other variable parts."""
    if not stderr_text:
        return "empty_error"
    # Normalize: remove line numbers, timestamps, memory addresses, PIDs
    normalized = re.sub(r'line \d+', 'line N', stderr_text)
    normalized = re.sub(r'\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}', 'TIMESTAMP', normalized)
    normalized = re.sub(r'\d{2}/\d{2}/\d{4}', 'DATE', normalized)
    normalized = re.sub(r'\d{2}:\d{2}:\d{2}', 'TIME', normalized)
    normalized = re.sub(r'0x[0-9a-fA-F]+', '0xADDR', normalized)
    normalized = re.sub(r'PID\s*\d+', 'PID N', normalized)
    # Take only the last meaningful error lines (last 500 chars)
    normalized = normalized.strip()[-500:]
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:12]


def can_attempt_heal(signature, state):
    """Check if we can attempt to fix this error (respects limits and cooldown)."""
    errors = state.get("errors", {})
    if signature not in errors:
        return True
    info = errors[signature]
    if info.get("count", 0) >= MAX_HEAL_ATTEMPTS:
        return False
    # Check cooldown
    last = info.get("last_attempt", "")
    if last:
        try:
            last_time = datetime.fromisoformat(last)
            elapsed = (datetime.now() - last_time).total_seconds()
            if elapsed < HEAL_COOLDOWN_SEC:
                return False
        except Exception:
            pass
    return True


def parse_crash_log():
    """Parse crash_log.txt and extract the most recent crash info.
    Returns dict with 'exit_code', 'stderr', 'timestamp' or None if no crash."""
    if not CRASH_LOG_FILE.exists():
        return None
    try:
        content = CRASH_LOG_FILE.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    if "===CRASH_START===" not in content:
        return None

    # Find the last crash block
    blocks = content.split("===CRASH_START===")
    if len(blocks) < 2:
        return None
    last_block = blocks[-1]
    # Extract fields
    crash_info = {"exit_code": "unknown", "stderr": "", "timestamp": ""}

    ts_match = re.search(r'timestamp=(.+)', last_block)
    if ts_match:
        crash_info["timestamp"] = ts_match.group(1).strip()

    ec_match = re.search(r'exit_code=(\S+)', last_block)
    if ec_match:
        crash_info["exit_code"] = ec_match.group(1).strip()

    # Extract stderr (everything between "--- stderr ---" and "===CRASH_END===")
    stderr_match = re.search(r'--- stderr ---\s*\n(.*?)(?:===CRASH_END===|\Z)', last_block, re.DOTALL)
    if stderr_match:
        crash_info["stderr"] = stderr_match.group(1).strip()

    # Skip clean kills (exit_code=-1 with no stderr = process was killed manually)
    if crash_info["exit_code"] == "-1" and not crash_info["stderr"]:
        return None

    # Only return if there's actual error content
    if crash_info["stderr"] or crash_info["exit_code"] not in ("0", "unknown"):
        return crash_info
    return None


def attempt_fix(crash_info):
    """Call Claude CLI to analyze and fix the crash error.
    Returns (success: bool, summary: str)."""
    stderr_snippet = crash_info["stderr"][:2000]  # Limit context size
    bot_file = os.path.abspath(str(SCRIPT_DIR / "telegram_secretary.py"))

    prompt = (
        f"你是 Telegram 秘书机器人的维修工。\n"
        f"上次运行崩溃了，错误信息如下：\n\n"
        f"退出码: {crash_info['exit_code']}\n"
        f"错误输出:\n{stderr_snippet}\n\n"
        f"请分析错误原因，然后直接修复文件:\n{bot_file}\n\n"
        f"注意：\n"
        f"- 只修复导致崩溃的问题，不要改其他功能\n"
        f"- 不要删除任何现有功能\n"
        f"- 修复后简要说明改了什么"
    )

    cmd = [
        NODE_EXE, CLAUDE_CLI_JS,
        "-p", prompt,
        "--output-format", "text",
        "--model", "sonnet",
        "--max-turns", "10",
        "--dangerously-skip-permissions",
    ]

    try:
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)

        result = subprocess.run(
            cmd,
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            timeout=HEAL_CLI_TIMEOUT,
            encoding="utf-8",
            errors="replace",
            shell=False,
            env=env,
        )
        output = result.stdout.strip()
        if result.returncode == 0 and output:
            # Extract a short summary (first 300 chars)
            summary = output[:300]
            return True, summary
        else:
            err = result.stderr.strip()[:200] if result.stderr else "no output"
            return False, f"CLI returned code {result.returncode}: {err}"
    except subprocess.TimeoutExpired:
        return False, "修复超时（2分钟）"
    except Exception as e:
        return False, f"修复出错: {str(e)[:200]}"


def archive_crash_log():
    """Clear crash_log.txt after processing (keep last 5 entries as archive)."""
    try:
        if CRASH_LOG_FILE.exists():
            content = CRASH_LOG_FILE.read_text(encoding="utf-8", errors="replace")
            blocks = content.split("===CRASH_START===")
            # Keep only header lines (non-crash content) for clean slate
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
        pass  # Don't let logging errors crash the bot


def self_heal():
    """Main self-heal entry point. Called at startup to check for previous crashes.
    If a crash is found, reports to user and attempts auto-fix via Claude CLI."""
    crash_info = parse_crash_log()
    if not crash_info:
        log("Self-heal: No crash detected, clean startup.")
        return

    stderr_short = crash_info["stderr"][:200] if crash_info["stderr"] else "(no stderr)"
    log(f"Self-heal: Crash detected! Exit code={crash_info['exit_code']}")
    log(f"Self-heal: stderr preview: {stderr_short}")

    # Check heal state
    state = load_heal_state()
    signature = get_error_signature(crash_info["stderr"])

    if not can_attempt_heal(signature, state):
        # Already tried too many times or in cooldown
        attempts = state.get("errors", {}).get(signature, {}).get("count", 0)
        log(f"Self-heal: Skipping fix (signature={signature}, attempts={attempts}/{MAX_HEAL_ATTEMPTS})")
        # Still report to user
        try:
            send_msg(
                f"老板，上次我崩溃了 (退出码: {crash_info['exit_code']})\n"
                f"错误: {stderr_short}\n\n"
                f"这个错误已经尝试修复{attempts}次了还是不行，需要老板亲自看看 🔧"
            )
        except Exception:
            pass
        archive_crash_log()
        return

    # Report and attempt fix
    try:
        send_msg(
            f"老板，检测到上次崩溃 (退出码: {crash_info['exit_code']})\n"
            f"错误: {stderr_short}\n\n"
            f"正在尝试自动修复... 🔧"
        )
    except Exception:
        pass

    success, summary = attempt_fix(crash_info)

    # Update heal state
    errors = state.setdefault("errors", {})
    if signature not in errors:
        errors[signature] = {
            "count": 0,
            "first_seen": datetime.now().isoformat(),
            "stderr_snippet": crash_info["stderr"][:100],
        }
    errors[signature]["count"] = errors[signature].get("count", 0) + 1
    errors[signature]["last_attempt"] = datetime.now().isoformat()
    save_heal_state(state)

    # Report result
    try:
        if success:
            send_msg(f"自动修复完成！\n修复内容: {summary[:500]}\n\n我会继续正常运行～")
        else:
            send_msg(f"自动修复失败了: {summary[:300]}\n\n需要老板介入看看 🆘")
    except Exception:
        pass

    archive_crash_log()
    log(f"Self-heal: {'SUCCESS' if success else 'FAILED'} — {summary[:100]}")


# ─── Memory ──────────────────────────────────────────────────────
def load_memory():
    """Load memory from JSON file."""
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "tasks": [],
        "notes": [],
        "history": [],
        "current_model": DEFAULT_MODEL,
        "cwd": DEFAULT_CWD
    }


def save_memory(memory):
    """Save memory to JSON file."""
    MEMORY_FILE.write_text(
        json.dumps(memory, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def add_history(memory, user_msg, response):
    """Add conversation summary to memory. Uses tiered memory:
    - history: last 50 detailed entries (recent conversations)
    - daily_summaries: compressed daily summaries, kept for 30 days
    When old entries get pushed out, they're compressed into daily summaries.
    """
    today = time.strftime("%m/%d")
    ts = time.strftime("%m/%d %H:%M")
    user_short = user_msg[:80].replace("\n", " ")
    resp_short = response[:120].replace("\n", " ")
    entry = f"[{ts}] 老板: {user_short} → 秘书: {resp_short}"

    history = memory.setdefault("history", [])
    history.append(entry)

    # Before trimming, compress old entries into daily summaries
    if len(history) > 50:
        # Entries that will be removed
        overflow = history[:-50]
        _compress_to_daily(memory, overflow)
        memory["history"] = history[-50:]

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

    # ── HAIKU: simple greetings, short casual chat ──
    haiku_greetings = [
        "你好", "早安", "午安", "晚安", "嗨", "hi", "hello", "hey",
        "谢谢", "好的", "ok", "收到", "嗯", "哦", "了解",
        "在吗", "在不在", "忙吗", "干嘛", "做什么",
    ]
    for g in haiku_greetings:
        if text_lower == g or (text_len < 8 and g in text_lower):
            return "haiku", "simple_chat"

    # Very short messages with no action keywords → haiku
    if text_len < 6 and not any(w in text_lower for w in ["查", "改", "做", "帮", "看", "写", "修"]):
        return "haiku", "very_short"

    # ── OPUS: complex tasks needing deep reasoning ──
    opus_keywords = [
        # Architecture & design
        "架构", "设计方案", "技术选型", "重构",
        # Deep analysis
        "分析一下", "详细分析", "深入分析", "全面检查", "诊断",
        # Planning & strategy
        "规划", "方案", "策略", "计划", "建议怎么",
        # Complex debugging
        "一直报错", "找不到原因", "不知道为什么", "很奇怪",
        # Multi-step / complex
        "整个系统", "所有项目", "全部", "从头到尾", "完整",
        # Code review
        "review", "代码审查", "代码质量", "优化整个",
        # Business logic
        "商业", "业务逻辑", "流程设计",
    ]
    for kw in opus_keywords:
        if kw in text_lower:
            return "opus", "complex_task"

    # Long messages (likely complex request) → opus
    if text_len > 200:
        return "opus", "long_request"

    # Messages with multiple questions/tasks → opus
    question_marks = text.count("?") + text.count("？")
    if question_marks >= 3:
        return "opus", "multi_question"

    # ── SONNET: everything else (balanced default) ──
    return "sonnet", "default"


# ─── Claude Code ─────────────────────────────────────────────────
def load_system_prompt():
    """Load system prompt from file."""
    if SYSTEM_PROMPT_FILE.exists():
        return SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
    return "你是AI秘书，用中文回复，像真人一样自然。"


def run_claude(prompt, memory, continue_session=True):
    """Run claude CLI and return the response text."""
    # Auto-select model based on task complexity
    model, reason = auto_select_model(prompt, memory)
    cwd = memory.get("cwd", DEFAULT_CWD)
    system_prompt = load_system_prompt()

    # Build context from tiered memory
    context_parts = []

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

    # Layer 2: Recent detailed history (last 10 messages)
    history = memory.get("history", [])
    if history:
        recent = "\n".join(history[-10:])
        context_parts.append(f"[最近对话记录]\n{recent}")

    # Combine context with current message
    if context_parts:
        context = "\n\n".join(context_parts)
        prompt = f"{context}\n\n[当前消息]\n{prompt}"

    # Build command — call node.exe + cli.js directly (NOT claude.cmd)
    # This avoids Windows cmd.exe which truncates args at newlines
    cmd = [NODE_EXE, CLAUDE_CLI_JS]
    if continue_session:
        cmd.append("-c")
    cmd += [
        "-p", prompt,
        "--output-format", "text",
        "--model", model,
        "--max-turns", str(MAX_TURNS),
        "--dangerously-skip-permissions",
        "--append-system-prompt", system_prompt,
    ]

    log(f"Running: claude -p (model={model} [{reason}], cwd={cwd})")

    # Remove CLAUDECODE env var to avoid "nested session" error
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)

    # Retry logic: up to 2 attempts for empty/failed results
    max_retries = 2
    for attempt in range(1, max_retries + 1):
        try:
            t_start = time.time()
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=CLAUDE_TIMEOUT,
                encoding="utf-8",
                errors="replace",
                shell=False,
                env=env
            )
            elapsed = time.time() - t_start
            output = result.stdout.strip()
            stderr = result.stderr.strip() if result.stderr else ""

            # Log diagnostics
            log(f"Claude CLI done: exit={result.returncode}, "
                f"stdout={len(output)}ch, stderr={len(stderr)}ch, "
                f"time={elapsed:.1f}s (attempt {attempt}/{max_retries})")

            if output:
                # Detect max turns hit
                if "Reached max turns" in output or "max turns" in output.lower():
                    return "⚠️ 老板，这次任务的操作步骤太多达到上限了。发条消息给我继续吧，我会接着做～"
                return output

            # No stdout — check stderr for clues
            if stderr:
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
            return f"（没有输出，运行了{elapsed:.0f}秒，退出码{result.returncode}）"

        except subprocess.TimeoutExpired:
            return f"老板，执行超时了（{CLAUDE_TIMEOUT//60}分钟）。要不要我换个方式试试？"
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
def log(msg):
    """Print log to console."""
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def main():
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
    log(f"Working directory: {memory.get('cwd', DEFAULT_CWD)}")
    log(f"Model: {memory.get('current_model', DEFAULT_MODEL)}")
    log(f"History entries: {len(memory.get('history', []))}")

    # Check for interrupted task from previous crash
    interrupted = memory.get("current_task")
    if interrupted and interrupted.get("status") == "processing":
        task_msg = interrupted.get("user_msg", "")
        task_time = interrupted.get("timestamp", "")
        log(f"Found interrupted task: {task_msg[:60]}...")
        restart_text = "秘书重新上线了!\n\n上次掉线前正在处理你的指令:\n" + task_msg[:100] + "\n\n需要我继续处理吗? 回复 继续 我就接着做"
        send_msg(restart_text)
        # Clear the interrupted task so we don't ask again on next restart
        memory["current_task"] = {"status": "interrupted_notified", "user_msg": task_msg}
        save_memory(memory)
    else:
        # Normal startup
        voice_status = "🎤 语音已启用" if VOICE_ENABLED else "⌨️ 仅文字模式"
        send_msg(f"🟢 秘书上线了！{voice_status}\n有什么吩咐随时说～")

    # Start daily reporter background thread (10:00 & 22:00)
    reporter = threading.Thread(target=daily_reporter_thread, daemon=True)
    reporter.start()
    log("Daily reporter started — will send at 10:00 & 22:00 daily")

    typing = TypingIndicator()
    offset = 0
    continue_session = False
    consecutive_errors = 0

    while True:
        try:
            # Long poll for updates
            resp = tg_api("getUpdates", {
                "offset": offset,
                "timeout": 30
            })

            if not resp.get("ok"):
                log(f"getUpdates failed: {resp.get('error', '?')}")
                time.sleep(5)
                continue

            for update in resp.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "").strip()
                caption = msg.get("caption", "").strip()

                # Security: only respond to configured chat ID or boss commands in GCFB group
                sender_id = str(msg.get("from", {}).get("id", ""))
                if chat_id != CHAT_ID:
                    # 允许老板在 GCFB 群里发命令
                    if GCFB_GROUP_CHAT_ID and chat_id == GCFB_GROUP_CHAT_ID and sender_id == BOSS_USER_ID:
                        log(f"Boss command from GCFB group: {text[:50]}")
                    else:
                        if chat_id == GCFB_GROUP_CHAT_ID:
                            log(f"Ignored non-boss message in GCFB group (sender: {sender_id})")
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
                        text = (text or caption or "") + f"\n[用户发了一张图片，已保存在: {path}]"

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

                # Handle /new: next claude call without -c
                if text == "/new":
                    continue_session = False
                    send_msg("好的老板，新对话开始了 🆕")
                    continue

                # Normal message → send to Claude Code
                # Immediately acknowledge receipt so user knows we're working
                send_msg("收到～正在处理中，稍等一下 ⏳")

                # Track current task in case of crash
                memory["current_task"] = {
                    "status": "processing",
                    "user_msg": text[:200],
                    "timestamp": time.strftime("%m/%d %H:%M")
                }
                save_memory(memory)

                typing.start()
                try:
                    response = run_claude(text, memory, continue_session)
                finally:
                    typing.stop()

                # Task completed — clear tracking
                memory["current_task"] = {"status": "done"}

                continue_session = True  # subsequent messages continue conversation

                # Parse any [CMD:...] and [FILE:...] tags
                response, reset_session = parse_cmd_tags(response, memory)
                if reset_session:
                    continue_session = False

                # Save conversation history
                add_history(memory, text, response)
                save_memory(memory)

                send_msg(response)
                log(f"Responded ({len(response)} chars)")
                consecutive_errors = 0  # Reset on successful processing

        except KeyboardInterrupt:
            log("Shutting down (Ctrl+C)")
            send_msg("🔴 秘书下线了")
            save_memory(memory)
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


def _query_lds():
    """Open LDS admin in Chrome, login, read today's stats. Returns text summary."""
    try:
        import pyautogui
        import time as _time

        sx, sy = 1920 / 1456, 1080 / 816

        def sc(x, y):
            return int(x * sx), int(y * sy)

        # Open new Chrome window with LDS
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-Command",
             f'Start-Process "chrome.exe" -ArgumentList "--new-window","{LDS_URL}"']
        )
        _time.sleep(8)

        # Dismiss any popup and wait for login page
        _take_screenshot()
        pyautogui.click(*sc(997, 134))
        _time.sleep(1)

        # Login
        pyautogui.click(*sc(1046, 444))
        _time.sleep(0.4)
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.typewrite(LDS_USER, interval=0.1)
        _time.sleep(0.3)
        pyautogui.press('tab')
        _time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.typewrite(LDS_PASS, interval=0.1)
        _time.sleep(0.3)
        pyautogui.press('enter')
        _time.sleep(6)

        # Take screenshot to read stats
        _take_screenshot()

        # Read image for text (use Claude vision via run_claude is too slow here,
        # so we use pyautogui to scroll down to see 7-day table then screenshot again)
        pyautogui.click(*sc(1200, 400))
        _time.sleep(0.3)
        pyautogui.press('pageup')  # go to top first
        _time.sleep(0.5)
        _take_screenshot()  # capture top stats: 总用户, 今日新用户, 今日抽奖

        # Read the numbers from screen by scrolling to the 7-day table
        pyautogui.press('pagedown')
        _time.sleep(1)
        _take_screenshot()

        # Close the LDS Chrome window
        pyautogui.hotkey('alt', 'F4')
        _time.sleep(1)

        return "LDS截图已采集"
    except Exception as e:
        log(f"LDS query error: {e}")
        return f"LDS查询失败: {e}"


def _query_booking():
    """Open Booking admin in Chrome, login, read today's bookings. Returns text summary."""
    try:
        import pyautogui
        import time as _time

        sx, sy = 1920 / 1456, 1080 / 816

        def sc(x, y):
            return int(x * sx), int(y * sy)

        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-Command",
             f'Start-Process "chrome.exe" -ArgumentList "--new-window","{BOOKING_URL}"']
        )
        _time.sleep(8)

        # Login
        pyautogui.click(*sc(1046, 444))
        _time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.typewrite(BOOKING_USER, interval=0.1)
        pyautogui.press('tab')
        _time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.typewrite(BOOKING_PASS, interval=0.1)
        pyautogui.press('enter')
        _time.sleep(5)

        _take_screenshot()

        pyautogui.hotkey('alt', 'F4')
        _time.sleep(1)

        return "预约截图已采集"
    except Exception as e:
        log(f"Booking query error: {e}")
        return f"预约查询失败: {e}"


def send_daily_report():
    """Compose and send the daily report by querying LDS + Booking via Chrome."""
    now = datetime.now()
    period = "早上" if now.hour < 12 else "晚上"
    log(f"Daily report triggered at {now.strftime('%H:%M')}")
    send_msg(f"⏰ {period} {now.strftime('%H:%M')} 自动汇报来了，正在查数据...")

    try:
        import pyautogui
        import time as _time

        sx, sy = 1920 / 1456, 1080 / 816

        def sc(x, y):
            return int(x * sx), int(y * sy)

        # ── Query LDS ──
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-Command",
             f'Start-Process "chrome.exe" -ArgumentList "--new-window","{LDS_URL}"']
        )
        _time.sleep(9)

        # Dismiss popup if any
        _take_screenshot()
        pyautogui.click(*sc(997, 134))
        _time.sleep(1)

        # Login LDS
        pyautogui.click(*sc(1046, 444))
        _time.sleep(0.4)
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.typewrite(LDS_USER, interval=0.1)
        pyautogui.press('tab')
        _time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.typewrite(LDS_PASS, interval=0.1)
        pyautogui.press('enter')
        _time.sleep(7)

        # Scroll to 7-day table area
        pyautogui.click(*sc(1200, 400))
        _time.sleep(0.3)
        pyautogui.press('pagedown')
        _time.sleep(1)
        lds_ss = _take_screenshot()

        # Read the LDS stats panel (top numbers are still visible in top bar)
        # Take one more screenshot to capture the full 7-day table
        pyautogui.press('pagedown')
        _time.sleep(0.8)
        _take_screenshot()

        # Scroll back to top to read top-bar numbers
        pyautogui.hotkey('ctrl', 'Home')
        _time.sleep(0.5)
        lds_top_ss = _take_screenshot()

        # Close LDS window
        pyautogui.hotkey('alt', 'F4')
        _time.sleep(1.5)

        # ── Query Booking ──
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-Command",
             f'Start-Process "chrome.exe" -ArgumentList "--new-window","{BOOKING_URL}"']
        )
        _time.sleep(9)

        # Login Booking
        pyautogui.click(*sc(1046, 444))
        _time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.typewrite(BOOKING_USER, interval=0.1)
        pyautogui.press('tab')
        _time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.typewrite(BOOKING_PASS, interval=0.1)
        pyautogui.press('enter')
        _time.sleep(6)

        booking_ss = _take_screenshot()

        # Close Booking window
        pyautogui.hotkey('alt', 'F4')
        _time.sleep(1)

        # ── Build report from screenshots using Claude ──
        date_str = now.strftime('%Y-%m-%d')
        prompt = (
            f"现在是 {now.strftime('%Y-%m-%d %H:%M')}，这是自动日报。\n"
            f"我刚才用 Chrome 截图了 LDS 抽奖系统和预约系统的数据，"
            f"截图已保存在 {SS_PATH}。\n"
            f"请读取最新的截图文件（{SS_PATH}），"
            "结合你在截图里看到的数字，整理成以下格式的汇报（纯文字，不要markdown）：\n\n"
            f"📊 {period}汇报 {date_str}\n\n"
            "【抽奖系统 LDS】\n"
            "总用户：xxx 人\n"
            "今日新用户：xxx 人\n"
            "今日抽奖：xxx 次\n"
            "待核销奖品：xxx 张\n\n"
            "【预约系统】\n"
            f"今日 {date_str} 预约共 x 张：\n"
            "列出每条预约（时间、姓名、人数、电话）\n\n"
            "如果截图里看不清某个数字，就写[查不到]。"
        )

        response = run_claude(prompt, {}, continue_session=False)
        response, _ = parse_cmd_tags(response, {})
        response = clean_markdown(response)

        send_msg(response)
        log("Daily report sent successfully")

    except ImportError:
        send_msg("自动汇报需要 pyautogui，请先安装：pip install pyautogui")
    except Exception as e:
        log(f"Daily report error: {e}")
        send_msg(f"自动汇报出错了 😅\n{str(e)[:200]}")


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


def daily_reporter_thread():
    """Background daemon thread: check time every minute, trigger report at 10:00 & 22:00."""
    sent_keys = set()   # (date_str, hour) pairs already sent today

    while True:
        try:
            now = datetime.now()
            if now.hour in REPORT_HOURS and now.minute == 0:
                key = (now.strftime("%Y-%m-%d"), now.hour)
                if key not in sent_keys:
                    sent_keys.add(key)
                    # Run in a separate thread so it doesn't block the reporter loop
                    t = threading.Thread(target=send_daily_report, daemon=True)
                    t.start()

            # Check scheduled one-off tasks (e.g. special report promised to boss)
            check_scheduled_tasks(now)

            # Clean up keys from previous days
            today = now.strftime("%Y-%m-%d")
            sent_keys = {k for k in sent_keys if k[0] == today}

        except Exception as e:
            log(f"Daily reporter loop error: {e}")

        time.sleep(60)


if __name__ == "__main__":
    main()
