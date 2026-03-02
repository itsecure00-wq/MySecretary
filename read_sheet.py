"""
Google Sheets 直读工具 — 用服务账号直接查询任意表格
用法: python read_sheet.py <SHEET_ID> <TAB_NAME> [RANGE]
例如: python read_sheet.py 1NAgyX8... 原始打卡数据 A1:M100
"""
import sys, json
from google.oauth2 import service_account
from googleapiclient.discovery import build

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

KEY_FILE = 'C:/Users/Admin23/.claude/service-account.json'
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

def get_service():
    creds = service_account.Credentials.from_service_account_file(KEY_FILE, scopes=SCOPES)
    return build('sheets', 'v4', credentials=creds)

def read_tab(sheet_id, tab_name, cell_range=None):
    svc = get_service()
    r = f"'{tab_name}'" if '!' not in tab_name else tab_name
    if cell_range:
        r = f"{r}!{cell_range}"
    result = svc.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=r
    ).execute()
    return result.get('values', [])

def list_tabs(sheet_id):
    svc = get_service()
    meta = svc.spreadsheets().get(spreadsheetId=sheet_id).execute()
    return [s['properties']['title'] for s in meta['sheets']]

# 已知 Sheet IDs
SHEETS = {
    'hrms': '1NAgyX8cbSrUkFYhylS6wcYPdSaLUVcaZgB_Ew31zcs4',
    'lds': '1l9lkBZiBRJb61aaPZh_aqa67Hc56NHoOvI8q40-Ik5Q',
    'booking': '1KfEaCUMRe4f-GNyDpTiTOwG3N_xw6bzC08-IvLrcHLA',
}

if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        print("用法: python read_sheet.py <sheet_id_or_alias> <tab_name> [range]")
        print("别名:", list(SHEETS.keys()))
        sys.exit(0)

    sheet_id = SHEETS.get(args[0], args[0])

    if len(args) == 1:
        tabs = list_tabs(sheet_id)
        print(json.dumps(tabs, ensure_ascii=False))
    else:
        tab = args[1]
        rng = args[2] if len(args) > 2 else None
        data = read_tab(sheet_id, tab, rng)
        print(json.dumps(data, ensure_ascii=False))
