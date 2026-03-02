# -*- coding: utf-8 -*-
import sys
import io
import os
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import urllib.request
import json
import ssl
import certifi

SSL_CTX = ssl.create_default_context(cafile=certifi.where())

# Load from .env if env vars not set
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().strip().splitlines():
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def send(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": CHAT_ID, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=15)
    return resp.status

msgs = [
    """早安老板！昨晚分析报告来了

最紧急要处理的5件事：

1. 密钥硬编码（所有系统）
- 小慧客服的 Claude API Key、Telegram Token 全部写死在代码里
- MySecretary 里 LDS密码888888、预约密码8888 也在源码里
- 一旦代码外泄，所有系统被接管

2. 预约系统密码明文存储
- 员工账号密码直接存在 Google Sheet 里，明文可见
- 建议：改为加密存储

3. HRMS 员工数据 API 公开
- 任何人知道 API 地址，就能拉到所有员工姓名+工号+部门
- 建议：API 只返回统计数字

4. 打卡照片存 6 个月（隐私+存储问题）
- 100员工 x 每天2张 x 180天 约 18GB
- 会超 Google Drive 免费额度
- 建议：改为保留 7 天

5. Telegram 通讯 SSL 验证被禁用
- 通讯可能被中间人拦截
- 建议修复证书问题""",

    """系统漏洞总结：

LDS 抽奖：
- 积分过期时间矛盾（注册30天 vs 系统配置90天）
- 理论上可以自己邀请自己刷积分

预约系统：
- 用户可以预约过去的日期（不报错）
- 被拒绝的订单仍占容量，名额计算错误
- Staff表被删会自动重建，默认密码8888

小慧客服：
- 对话6小时过期就完全消失，预约信息可能丢失
- 没有用量限制，可被刷屏消耗 Claude API 额度

HRMS：
- GPS打卡坐标明文存储，员工住址可被推算
- OT计算与不同班次工时不匹配，可能有计算误差""",

    """建议新功能（按价值排序）：

高价值（建议先做）：
1. LDS 欺诈检测 - 检测同设备多次注册、自己邀请自己
2. 预约自动提醒 - 确认后发WhatsApp，预约前1小时再提醒
3. 考勤异常告警 - 员工连续迟到3天自动通知老板
4. HRMS 月度薪资报告 - 自动生成，可导出 Excel
5. 小慧 FAQ 模板 - 常见问题不调用 Claude，省费用

中价值：
6. 预约桌位分配系统
7. LDS 年度排行榜
8. HRMS 银行代发薪水文件

安全评分：
- LDS 抽奖：安全55 / 稳定70
- HRMS 人事：安全50 / 稳定65
- 小慧客服：安全40（最弱）
- 预约系统：安全45
- 秘书机器人：安全35（最危险）

老板想优先处理哪一块？我马上开干"""
]

for i, msg in enumerate(msgs):
    status = send(msg)
    print(f"第{i+1}段: {status}")
