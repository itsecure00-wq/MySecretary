#!/usr/bin/env python3
"""
Telegram AI Secretary — 远程遥控 Claude Code
通过 Telegram 和 AI 秘书对话，秘书自动调 Claude Code 执行编码任务。
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

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
    str(Path.home() / "Documents" / "code" / "hrms")
)


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
        with urllib.request.urlopen(req, timeout=30) as r:
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
    cmd = ["claude"]
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
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
            encoding="utf-8",
            errors="replace"
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
            f"待办任务：{len(pending)} 个"
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
    log("=" * 50)

    memory = load_memory()
    log(f"Working directory: {memory.get('cwd', DEFAULT_CWD)}")
    log(f"Model: {memory.get('current_model', DEFAULT_MODEL)}")

    # Send startup notification
    send_msg("🟢 秘书上线了！有什么吩咐随时说～")

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

                if not text:
                    continue

                # Security: only respond to configured chat ID
                if chat_id != CHAT_ID:
                    log(f"Ignored message from unknown chat: {chat_id}")
                    continue

                log(f"Received: {text[:80]}...")

                # Handle special commands
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
                send_msg("收到，让我看看... 🤔")

                response = run_claude(text, memory, continue_session)
                continue_session = True  # subsequent messages continue conversation

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
