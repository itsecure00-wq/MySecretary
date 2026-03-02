"""
backup_memory.py - 自动备份 Claude 记忆文件到 Google Sheets
备份内容:
  - MEMORY.md (Claude 的跨会话记忆)
  - .env 的 key 名称模板（值不备份）

备份位置: HRMS Google Sheet → 'AI记忆备份' 工作表
"""

import os
import sys
import datetime
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_FILE = r"C:\Users\Admin23\.claude\projects\C--Users-Admin23-Documents-cluade-code\memory\MEMORY.md"
SERVICE_ACCOUNT_FILE = r"C:\Users\Admin23\.claude\service-account.json"
ENV_FILE = os.path.join(SCRIPT_DIR, ".env")
HRMS_SHEET_ID = "1NAgyX8cbSrUkFYhylS6wcYPdSaLUVcaZgB_Ew31zcs4"
BACKUP_SHEET_NAME = "AI记忆备份"

def get_sheets_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('sheets', 'v4', credentials=creds)

def ensure_backup_sheet(service):
    """确保备份工作表存在"""
    meta = service.spreadsheets().get(spreadsheetId=HRMS_SHEET_ID).execute()
    sheets = [s['properties']['title'] for s in meta['sheets']]
    if BACKUP_SHEET_NAME not in sheets:
        body = {'requests': [{'addSheet': {'properties': {'title': BACKUP_SHEET_NAME}}}]}
        service.spreadsheets().batchUpdate(spreadsheetId=HRMS_SHEET_ID, body=body).execute()
        print(f"已创建工作表: {BACKUP_SHEET_NAME}")

def backup_memory():
    """执行备份"""
    try:
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{now}] 开始备份...")
        service = get_sheets_service()
        ensure_backup_sheet(service)

        rows = []
        rows.append([f"=== 备份时间: {now} ==="])
        rows.append([""])

        # 1. MEMORY.md 内容
        rows.append(["--- MEMORY.md ---"])
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                for line in f.readlines():
                    rows.append([line.rstrip()])
            print("已读取 MEMORY.md")
        else:
            rows.append([f"找不到文件: {MEMORY_FILE}"])

        rows.append([""])

        # 2. .env key 名称模板
        rows.append(["--- .env 配置项（值已隐藏）---"])
        if os.path.exists(ENV_FILE):
            with open(ENV_FILE, 'r', encoding='utf-8') as f:
                for line in f.readlines():
                    line = line.strip()
                    if '=' in line and not line.startswith('#'):
                        key = line.split('=')[0]
                        rows.append([f"{key}=<实际值请查看 .env>"])
                    elif line:
                        rows.append([line])

        # 清空旧内容再写入
        service.spreadsheets().values().clear(
            spreadsheetId=HRMS_SHEET_ID,
            range=f"{BACKUP_SHEET_NAME}!A1:A2000"
        ).execute()

        service.spreadsheets().values().update(
            spreadsheetId=HRMS_SHEET_ID,
            range=f"{BACKUP_SHEET_NAME}!A1",
            valueInputOption='RAW',
            body={'values': rows}
        ).execute()

        print(f"备份完成！共 {len(rows)} 行写入 HRMS Sheet → {BACKUP_SHEET_NAME}")
        return True

    except Exception as e:
        print(f"备份失败: {e}")
        return False

if __name__ == '__main__':
    backup_memory()
