# Claude 秘书系统 — 自动安装指南

你是"小助手"，老板的 AI 秘书。这份文件包含你需要的一切来完成自动安装。
老板会在新电脑上把这个文件给你，你按照下面的步骤自动执行，全部装好。

## 第一步：检查基础软件

检查并安装以下软件（如果还没装）：

```bash
# 检查 Node.js
node --version || echo "需要安装 Node.js: https://nodejs.org"

# 检查 Python
python --version || python3 --version || echo "需要安装 Python: https://python.org"

# 检查 Git
git --version || echo "需要安装 Git: https://git-scm.com"

# 安装 clasp (Google Apps Script CLI)
npm install -g @google/clasp
```

## 第二步：创建工作目录

```bash
mkdir -p "C:/Users/$USERNAME/Documents/cluade code"
cd "C:/Users/$USERNAME/Documents/cluade code"
```

## 第三步：克隆所有项目

```bash
git clone https://github.com/itsecure00-wq/MySecretary.git
git clone https://github.com/itsecure00-wq/HRMS.git
git clone https://github.com/itsecure00-wq/LDS.git
git clone https://github.com/itsecure00-wq/Booking-system.git "booking system"
git clone https://github.com/itsecure00-wq/Advertise-Sys.git
git clone https://github.com/itsecure00-wq/gcfb-marketing.git
git clone https://github.com/itsecure00-wq/inventory.git
```

chat-service 不是 git 项目，从 Google Apps Script 拉取：
```bash
mkdir chat-service && cd chat-service
clasp clone 1r-y3JobLhjHpKMFRIz8Raz3tF6PNi0-sX4TDZvrIhw26aVlCeyznMlFi
cd ..
```

## 第四步：安装 Python 依赖

```bash
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client requests certifi
```

## 第五步：从 Google Drive 下载凭证

备份文件在老板的 Google Drive 文件夹：
https://drive.google.com/drive/folders/1Lu55IufKvW-DhoSLmy2uMZSLU8oWn217

需要下载 3 个文件：

1. `service-account.json` → 放到 `C:/Users/<用户名>/.claude/service-account.json`
2. `.env` → 放到 `MySecretary/.env`
3. `MEMORY.md` → 放到 `C:/Users/<用户名>/.claude/projects/C--Users-<用户名>-Documents-cluade-code/memory/MEMORY.md`

告诉老板：「打开 Google Drive 的 Claude秘书备份 文件夹，把 3 个文件下载到桌面，我来放到对的位置」

```bash
# 创建 memory 目录 (路径里的用户名要改成实际的)
mkdir -p "C:/Users/$USERNAME/.claude/projects/C--Users-$USERNAME-Documents-cluade-code/memory"
```

## 第六步：配置 clasp

```bash
clasp login
```
让老板用 it.secure00@gmail.com 登录。

## 第七步：创建 CLAUDE.md

在工作目录下创建 CLAUDE.md，把 MEMORY.md 的内容也合并进去。
CLAUDE.md 是你的项目指令文件，Claude Code 每次启动都会读它。

## 第八步：启动秘书机器人

```bash
cd MySecretary
# Windows:
start_secretary.bat
```

## 第九步：验证

逐个检查：
```bash
# 1. Google Sheets 读取
cd MySecretary && python read_sheet.py hrms 员工资料 A1:C3

# 2. 备份功能
python backup_memory.py

# 3. 各系统 API
curl "https://script.google.com/macros/s/AKfycbwfbid1aSjvz3jsBGrY7s_Yd5CTBZe9_16v2xyDRSWp11WhEB7HHTYmz-xGpeYsiqR1xg/exec?page=api&key=zchhp2024"
```

## 系统清单

| 系统 | 路径 | 类型 | Script ID |
|------|------|------|-----------|
| HRMS 人事 | HRMS/ | GAS (clasp) | 16eeuLegOQaMLrIdz6iFc3WXYXQdCi0MDgY739W8UzqxeRKbxc4VZZR1J |
| 小慧客服 | chat-service/ | GAS (clasp) | 1r-y3JobLhjHpKMFRIz8Raz3tF6PNi0-sX4TDZvrIhw26aVlCeyznMlFi |
| LDS 抽奖 | LDS/ | GitHub + GAS | — |
| 预约系统 | booking system/ | GitHub + GAS | — |
| 秘书机器人 | MySecretary/ | Python + Telegram | — |
| DocuScan Pro | docuscan-pro/ | Next.js + Supabase | — |
| 广告系统 | Advertise-Sys/ | TypeScript | — |

## 关键凭证说明

| 凭证 | 来源 | 用途 |
|------|------|------|
| Telegram Bot Token | @BotFather | 秘书机器人 |
| Anthropic API Key | console.anthropic.com | Claude AI |
| service-account.json | Google Cloud Console → huihotpot-lds 项目 | 读写 Google Sheets |
| HRMS API Key | GAS Script Properties → API_SECRET_KEY | HRMS API 访问 |

## Google Sheets ID

| 表格 | Sheet ID |
|------|----------|
| HRMS | 1NAgyX8cbSrUkFYhylS6wcYPdSaLUVcaZgB_Ew31zcs4 |
| LDS | 1l9lkBZiBRJb61aaPZh_aqa67Hc56NHoOvI8q40-Ik5Q |
| Booking | 1KfEaCUMRe4f-GNyDpTiTOwG3N_xw6bzC08-IvLrcHLA |

## 服务账号

claude-sheets@huihotpot-lds.iam.gserviceaccount.com
所有需要读写的 Google Sheet 都要共享给这个账号（编辑者权限）。

## Telegram 配置

- Bot: @Gcfbboss_bot (Homebot)
- 老板 Chat ID: 7560692069
- GCFB 群 Chat ID: -1003745039353

## 部署命令速查

```bash
# HRMS 部署
cd HRMS/apps-script-temp && clasp push --force && clasp deploy -i AKfycbwfbid1aSjvz3jsBGrY7s_Yd5CTBZe9_16v2xyDRSWp11WhEB7HHTYmz-xGpeYsiqR1xg

# 小慧客服部署
cd chat-service && clasp push --force && clasp deploy -i AKfycbw45op0Bqn4E8iHIbVLdGi-cLWFt-rEiEooWzwiynd6zIv6WoR7X9vIShdzIjTAa-_v
```

---

安装完成后，告诉老板：「系统已恢复完毕，所有功能正常运作！」
