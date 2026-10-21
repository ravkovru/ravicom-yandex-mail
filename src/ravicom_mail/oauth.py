"""Yandex OAuth device authorization helpers; no token persistence."""
import os, time, httpx
AUTHORIZE="https://oauth.yandex.com/device/code"
TOKEN="https://oauth.yandex.com/token"
class OAuthError(RuntimeError): pass

def request_device_code(client_id,scope="mail:imap_full"):
    r=httpx.post(AUTHORIZE,data={"client_id":client_id,"scope":scope},timeout=20); r.raise_for_status(); return r.json()

def poll_device_token(client_id,client_secret,device_code,interval=5,expires_in=600):
    deadline=time.monotonic()+expires_in
    while time.monotonic()<deadline:
        r=httpx.post(TOKEN,data={"grant_type":"device_code","code":device_code,"client_id":client_id,"client_secret":client_secret},timeout=20); data=r.json()
        if r.is_success and data.get("access_token"): return data["access_token"]
        error=data.get("error")
        if error in {"authorization_pending","slow_down"}: time.sleep(interval+(5 if error=="slow_down" else 0)); continue
        raise OAuthError(f"Yandex OAuth failed: {error or r.status_code}")
    raise OAuthError("Yandex OAuth device code expired")

def access_token():
    token=os.getenv("YANDEX_ACCESS_TOKEN","").strip()
    if not token: raise OAuthError("Set YANDEX_ACCESS_TOKEN; run scripts/oauth_device_flow.py")
    return token
