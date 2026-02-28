# Telegram AI Secretary

Telegram 上的 AI 秘书，远程遥控 Claude Code。
从手机发消息，秘书自动执行编码任务并汇报。

## 安装步骤

### 1. 前置要求
- Python 3.12+
- Claude Code CLI (`npm i -g @anthropic-ai/claude-code`)
- Claude Code 已登录 (`claude` 能正常运行)

### 2. 配置
编辑 `start_secretary.bat`，填入你的 Telegram Bot Token 和 Chat ID：
```
set TELEGRAM_BOT_TOKEN=你的token
set TELEGRAM_CHAT_ID=你的chatid
```

或者设置为系统环境变量。

### 3. 启动
双击 `start_secretary.bat`

### 4. 使用
在 Telegram 上给 bot 发消息即可，秘书会自动回复。

## 特殊命令

| 命令 | 功能 |
|------|------|
| `/new` | 开始新对话 |
| `/cd <path>` | 切换工作目录 |
| `/model opus/sonnet/haiku` | 切换 AI 模型 |
| `/status` | 查看当前状态 |
| `/tasks` | 查看待办任务 |
| `/stop` | 停止秘书 |

## 文件说明

| 文件 | 用途 |
|------|------|
| `telegram_secretary.py` | 主程序 |
| `system_prompt.txt` | 秘书人格定义（可自定义） |
| `memory.json` | 记忆存储（自动生成） |
| `start_secretary.bat` | Windows 启动脚本 |
