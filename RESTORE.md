# Claude 秘书系统 — 灾难恢复指南

**目标**: 电脑坏了/换新机，在最短时间内完全恢复 Claude 秘书及所有系统记忆

---

## 预计恢复时间: 约 60-90 分钟

---

## 第一步：安装基础软件（30分钟）

```
1. Node.js — https://nodejs.org  (选 LTS 版)
2. Python 3.x — https://python.org
3. Git — https://git-scm.com
4. Claude CLI — 安装完 Node.js 后运行:
   npm install -g @anthropic-ai/claude-code
5. clasp (Google Apps Script CLI):
   npm install -g @google/clasp
```

Claude CLI 安装路径通常在: `C:\Users\<用户名>\nodejs\claude.cmd`

---

## 第二步：克隆所有项目（5分钟）

在目标目录（如 `C:\Users\<用户名>\Documents\cluade code`）运行:

```bash
git clone https://github.com/itsecure00-wq/MySecretary.git
git clone https://github.com/itsecure00-wq/HRMS.git
git clone https://github.com/itsecure00-wq/LDS.git
git clone https://github.com/itsecure00-wq/Booking-system.git
git clone https://github.com/itsecure00-wq/Advertise-Sys.git
git clone https://github.com/itsecure00-wq/gcfb-marketing.git
git clone https://github.com/itsecure00-wq/inventory.git
```

chat-service (小慧客服) — 从 Google Apps Script 拉取:
```bash
mkdir chat-service && cd chat-service
clasp clone AKfycbw45op0Bqn4E8iHIbVLdGi-cLWFt-rEiEooWzwiynd6zIv6WoR7X9vIShdzIjTAa-_v
```

---

## 第三步：恢复 Claude 记忆（10分钟）

记忆备份在 HRMS Google Sheet → "AI记忆备份" 工作表

1. 打开 HRMS Sheet: https://docs.google.com/spreadsheets/d/1NAgyX8cbSrUkFYhylS6wcYPdSaLUVcaZgB_Ew31zcs4
2. 找到 "AI记忆备份" 工作表，复制 MEMORY.md 的内容
3. 新建目录: `C:\Users\<用户名>\.claude\projects\C--Users-Admin23-Documents-cluade-code\memory\`
4. 创建 `MEMORY.md` 文件，粘贴内容保存

---

## 第四步：恢复凭证（15分钟）

### .env 文件
在 `MySecretary/.env` 创建以下内容（填入实际值）:

```
TELEGRAM_BOT_TOKEN=<从 BotFather 获取>
TELEGRAM_CHAT_ID=<你的 Telegram 用户 ID>
GCFB_GROUP_CHAT_ID=-1003745039353
LDS_USER=boss
LDS_PASS=<LDS 管理员密码>
BOOKING_USER=boss
BOOKING_PASS=<预约系统密码>
```

### service-account.json
- 登录 Google Cloud Console: https://console.cloud.google.com
- 项目: huihotpot-lds
- IAM → 服务账号 → claude-sheets@huihotpot-lds.iam.gserviceaccount.com
- 创建新密钥 → JSON → 下载
- 保存到: `C:\Users\<用户名>\.claude\service-account.json`

### Anthropic API Key
- 登录: https://console.anthropic.com
- API Keys → 创建新 Key
- 在 Claude CLI 第一次运行时会要求输入

---

## 第五步：安装 Python 依赖（5分钟）

```bash
cd MySecretary
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
pip install requests certifi
```

---

## 第六步：配置 clasp（5分钟）

```bash
clasp login
```
用 it.secure00@gmail.com 登录

---

## 第七步：启动秘书机器人（5分钟）

```bash
cd MySecretary
start_secretary.bat
```

---

## 验证清单

- [ ] Claude 能通过 Telegram 回复消息
- [ ] `python backup_memory.py` 运行成功
- [ ] `python read_sheet.py hrms 员工资料 A1:C5` 能读取数据
- [ ] HRMS 系统可以在浏览器访问
- [ ] 小慧客服链接可以正常对话

---

## 重要链接备忘

| 系统 | 链接 |
|------|------|
| HRMS | https://script.google.com/macros/s/AKfycbwfbid1aSjvz3jsBGrY7s_Yd5CTBZe9_16v2xyDRSWp11WhEB7HHTYmz-xGpeYsiqR1xg/exec |
| 小慧客服 | https://script.google.com/macros/s/AKfycbw45op0Bqn4E8iHIbVLdGi-cLWFt-rEiEooWzwiynd6zIv6WoR7X9vIShdzIjTAa-_v/exec |
| LDS 抽奖 | https://script.google.com/macros/s/AKfycbzTxymBxmmliLWpOdg-lh-Ev6tDKyjEf91wgTaDAtxx0gtEsZZrsL9rL9AFv7-XaySlew/exec |
| 预约系统 | https://script.google.com/macros/s/AKfycbyq1uhgRek_xCtOeAeWnS6mKxoYI4FMSiezAHlGHB-GXkJNGIZNTaotIT76CmKNvoY_/exec |
| HRMS Sheet | https://docs.google.com/spreadsheets/d/1NAgyX8cbSrUkFYhylS6wcYPdSaLUVcaZgB_Ew31zcs4 |

---

*最后更新: 2026-03-02*
