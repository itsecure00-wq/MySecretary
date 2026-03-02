"""
backup_memory.py - 自动备份 Claude 记忆和凭证到 Google Drive + Google Sheets
备份内容:
  - MEMORY.md         → Google Drive (可直接下载) + HRMS Sheet (可直接阅读)
  - service-account.json → Google Drive
  - .env 完整内容    → Google Drive

备份位置:
  Drive: https://drive.google.com/drive/folders/1Lu55IufKvW-DhoSLmy2uMZSLU8oWn217
  Sheet: HRMS Google Sheet → 'AI记忆备份' 工作表
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

HRMS_SHEET_ID     = "1NAgyX8cbSrUkFYhylS6wcYPdSaLUVcaZgB_Ew31zcs4"
BACKUP_SHEET_NAME = "AI记忆备份"
DRIVE_FOLDER_ID   = "1Lu55IufKvW-DhoSLmy2uMZSLU8oWn217"
HRMS_API_URL      = ("https://script.google.com/macros/s/"
                     "AKfycbwfbid1aSjvz3jsBGrY7s_Yd5CTBZe9_16v2xyDRSWp11WhEB7HHTYmz-xGpeYsiqR1xg"
                     "/exec")
HRMS_API_KEY      = "zchhp2024"


# ─── Google API helpers ───────────────────────────────────────────────────────

def _creds(scopes):
    from google.oauth2 import service_account
    return service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=scopes)

def get_sheets_service():
    from googleapiclient.discovery import build
    return build('sheets', 'v4',
                 credentials=_creds(['https://www.googleapis.com/auth/spreadsheets']))


# ─── Drive upload via HRMS GAS proxy ─────────────────────────────────────────

def drive_upload_via_gas(filename, content_str):
    """Upload a file to Google Drive via HRMS GAS backup endpoint."""
    import json, urllib.request, ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    url = f"{HRMS_API_URL}?page=backup&key={HRMS_API_KEY}"
    payload = json.dumps({
        'filename': filename,
        'content': content_str,
        'folderId': DRIVE_FOLDER_ID
    }).encode('utf-8')

    req = urllib.request.Request(url, data=payload,
                                  headers={'Content-Type': 'application/json'},
                                  method='POST')
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        result = json.loads(r.read().decode('utf-8'))

    if result.get('success'):
        print(f"  Drive 上传成功: {filename}")
    else:
        raise Exception(result.get('error', 'unknown error'))


# ─── Sheets backup ────────────────────────────────────────────────────────────

def backup_to_sheet(sheets, now_str, memory_content):
    """Write MEMORY.md content to HRMS Sheet for easy reading."""
    # Ensure sheet exists
    meta = sheets.spreadsheets().get(spreadsheetId=HRMS_SHEET_ID).execute()
    existing_sheets = [s['properties']['title'] for s in meta['sheets']]
    if BACKUP_SHEET_NAME not in existing_sheets:
        body = {'requests': [{'addSheet': {'properties': {'title': BACKUP_SHEET_NAME}}}]}
        sheets.spreadsheets().batchUpdate(spreadsheetId=HRMS_SHEET_ID, body=body).execute()

    rows = [[f"=== 备份时间: {now_str} ==="],[""]]
    rows.append(["--- MEMORY.md ---"])
    for line in memory_content.splitlines():
        rows.append([line])

    sheets.spreadsheets().values().clear(
        spreadsheetId=HRMS_SHEET_ID,
        range=f"{BACKUP_SHEET_NAME}!A1:A2000").execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=HRMS_SHEET_ID,
        range=f"{BACKUP_SHEET_NAME}!A1",
        valueInputOption='RAW',
        body={'values': rows}).execute()
    print(f"  Sheet 更新: {BACKUP_SHEET_NAME} ({len(rows)} 行)")


# ─── Main ─────────────────────────────────────────────────────────────────────

def backup_memory():
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now_str}] 开始备份...")

    errors = []

    # ── 读取所有要备份的文件 ──
    memory_content = ""
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
            memory_content = f.read()
        print(f"  读取 MEMORY.md ({len(memory_content)} 字符)")
    else:
        errors.append(f"找不到 MEMORY.md: {MEMORY_FILE}")

    env_content = ""
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, 'r', encoding='utf-8') as f:
            env_content = f.read()
        print(f"  读取 .env ({len(env_content.splitlines())} 行)")

    sa_content = ""
    if os.path.exists(SERVICE_ACCOUNT_FILE):
        with open(SERVICE_ACCOUNT_FILE, 'r', encoding='utf-8') as f:
            sa_content = f.read()
        print(f"  读取 service-account.json")

    # ── Google Drive 备份（通过 HRMS GAS 中转）──
    try:
        if memory_content:
            drive_upload_via_gas('MEMORY.md', memory_content)
        if env_content:
            drive_upload_via_gas('.env', env_content)
        if sa_content:
            drive_upload_via_gas('service-account.json', sa_content)
        print("  Google Drive 备份完成 ✓")
    except Exception as e:
        errors.append(f"Drive 备份失败: {e}")
        print(f"  Drive 备份失败: {e}")

    # ── Google Sheets 备份 (MEMORY.md 便于阅读) ──
    try:
        sheets = get_sheets_service()
        backup_to_sheet(sheets, now_str, memory_content or "(空)")
        print("  Google Sheets 备份完成 ✓")
    except Exception as e:
        errors.append(f"Sheets 备份失败: {e}")
        print(f"  Sheets 备份失败: {e}")

    if errors:
        print(f"\n备份完成（有 {len(errors)} 个警告）:")
        for e in errors:
            print(f"  ⚠ {e}")
        return False
    else:
        print(f"\n全部备份成功！")
        return True


if __name__ == '__main__':
    backup_memory()
