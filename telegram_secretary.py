#!/usr/bin/env python3
"""
Telegram AI Secretary — 远程遥控 Claude Code
通过 Telegram 和 AI 秘书对话，秘书自动调 Claude Code 执行编码任务。
支持语音消息：发送语音 → 自动转文字 → 交给 Claude 处理
"""

import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.parse
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

# SSL workaround for Windows certificate issues
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# ─── Configuration ───────────────────────────────────────────────
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SCRIPT_DIR = Path(__file__).parent
MEMORY_FILE = SCRIPT_DIR / "memory.json"
SYSTEM_PROMPT_FILE = SCRIPT_DIR / "system_prompt.txt"
CLAUDE_TIMEOUT = 300  # 5 minutes max per command
MAX_TURNS = 15
DEFAULT_MODEL = "sonnet"
DEFAULT_CWD = os.environ.get(
    "SECRETARY_CWD",
    str(Path.home() / "Documents" / "cluade code")
)
CLAUDE_CMD = os.environ.get(
    "CLAUDE_CMD",
    r"C:\Users\Admin23\nodejs\claude.cmd"
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


# ─── Telegram API ────────────────────────────────────────────────
def tg_api(method, params=None):
    """Call Telegram Bot API."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        if params:
            data = urllib.parse.urlencode(params).encode("utf-8")
            req = urllib.request.Request(url, data=data)
        else:
            req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        log(f"Telegram API error: {e}")
        return {"ok": False, "error": str(e)}


def send_msg(text, chat_id=None):
    """Send message to Telegram, auto-splitting long messages."""
    cid = chat_id or CHAT_ID
    # Telegram limit is 4096 chars
    chunks = split_message(text, 4000)
    for chunk in chunks:
        tg_api("sendMessage", {
            "chat_id": cid,
            "text": chunk,
            "parse_mode": "HTML"
        })
        if len(chunks) > 1:
            time.sleep(0.5)  # avoid rate limit


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


def transcribe_voice(ogg_path):
    """Convert OGG voice to text using Google Speech Recognition (Chinese)."""
    if not VOICE_ENABLED:
        return None
    wav_path = ogg_path.replace(".ogg", ".wav")
    try:
        # Convert OGG → WAV using pydub + ffmpeg
        audio = AudioSegment.from_ogg(ogg_path)
        audio.export(wav_path, format="wav")

        # Recognize speech (Google free API, supports Chinese)
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
        text = recognizer.recognize_google(audio_data, language="zh-CN")
        return text
    except sr.UnknownValueError:
        return None  # Could not understand
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
        "current_model": DEFAULT_MODEL,
        "cwd": DEFAULT_CWD
    }


def save_memory(memory):
    """Save memory to JSON file."""
    MEMORY_FILE.write_text(
        json.dumps(memory, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# ─── Claude Code ─────────────────────────────────────────────────
def load_system_prompt():
    """Load system prompt from file."""
    if SYSTEM_PROMPT_FILE.exists():
        return SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
    return "你是AI秘书，用中文回复，像真人一样自然。"


def run_claude(prompt, memory, continue_session=True):
    """Run claude CLI and return the response text."""
    model = memory.get("current_model", DEFAULT_MODEL)
    cwd = memory.get("cwd", DEFAULT_CWD)
    system_prompt = load_system_prompt()

    # Build command
    cmd = [CLAUDE_CMD]
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

    log(f"Running: claude -p (model={model}, cwd={cwd})")

    try:
        # Remove CLAUDECODE env var to avoid "nested session" error
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)

        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
            encoding="utf-8",
            errors="replace",
            shell=True,  # Required for .cmd files on Windows
            env=env
        )
        output = result.stdout.strip()
        if not output and result.stderr:
            output = f"执行时遇到问题：{result.stderr.strip()[:500]}"
        return output or "（没有输出）"
    except subprocess.TimeoutExpired:
        return "老板，这个任务太复杂了，执行超时了（5分钟）。要不要我换个方式试试？"
    except FileNotFoundError:
        return "老板，我找不到 claude 命令。请确保 Claude Code CLI 已安装。"
    except Exception as e:
        return f"执行出错了：{str(e)[:200]}"


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
        return (
            f"📊 当前状态\n"
            f"工作目录：{c}\n"
            f"模型：{m}\n"
            f"待办任务：{len(pending)} 个\n"
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
        if model in ("opus", "sonnet", "haiku"):
            memory["current_model"] = model
            return f"🧠 模型已切换到 {model}", True
        return "❌ 可选模型：opus / sonnet / haiku", False

    if text == "/stop":
        return "__STOP__", False

    return None, False  # Not a command


def parse_cmd_tags(response, memory):
    """Parse [CMD:...] tags from Claude's response and execute them."""
    changed = False
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
            changed = True  # Signal to reset session
            log("Auto-executed: /new")
    if changed:
        save_memory(memory)
    return response, changed


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

    memory = load_memory()
    log(f"Working directory: {memory.get('cwd', DEFAULT_CWD)}")
    log(f"Model: {memory.get('current_model', DEFAULT_MODEL)}")

    # Send startup notification
    voice_status = "🎤 语音已启用" if VOICE_ENABLED else "⌨️ 仅文字模式"
    send_msg(f"🟢 秘书上线了！{voice_status}\n有什么吩咐随时说～")

    offset = 0
    continue_session = False

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

                # Security: only respond to configured chat ID
                if chat_id != CHAT_ID:
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
                            if text:
                                log(f"Voice transcribed: {text[:80]}...")
                            else:
                                send_msg("抱歉老板，没听清楚，能再说一次吗？ 🙉")
                                continue
                        else:
                            send_msg("语音下载失败了，请重新发送")
                            continue

                if not text:
                    continue

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
                response = run_claude(text, memory, continue_session)
                continue_session = True  # subsequent messages continue conversation

                # Parse any [CMD:...] tags from Claude's response
                response, had_cmd = parse_cmd_tags(response, memory)
                if had_cmd and "new" in str(had_cmd):
                    continue_session = False

                send_msg(response)
                log(f"Responded ({len(response)} chars)")

        except KeyboardInterrupt:
            log("Shutting down (Ctrl+C)")
            send_msg("🔴 秘书下线了")
            save_memory(memory)
            break
        except Exception as e:
            log(f"Error in main loop: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
