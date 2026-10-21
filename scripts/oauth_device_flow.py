#!/usr/bin/env python3
import os, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from dotenv import load_dotenv
from ravicom_mail.oauth import request_device_code,poll_device_token
load_dotenv()
client_id=os.getenv("YANDEX_CLIENT_ID"); secret=os.getenv("YANDEX_CLIENT_SECRET")
if not client_id or not secret: raise SystemExit("Set YANDEX_CLIENT_ID and YANDEX_CLIENT_SECRET in .env")
info=request_device_code(client_id)
print(f"Open {info.get('verification_url','https://ya.ru/device')} and enter code: {info['user_code']}")
print("Waiting for authorization…")
token=poll_device_token(client_id,secret,info["device_code"],int(info.get("interval",5)),int(info.get("expires_in",600)))
print("Authorization succeeded. Copy this token into YANDEX_ACCESS_TOKEN in .env; do not share it.")
print(token)
