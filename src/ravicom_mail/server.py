"""OpenAI-compatible MCP tools for Yandex Mail."""
import hmac, os, hashlib, json, time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from . import imap_client as mail

load_dotenv()
PREVIEWS = {}


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Protect the remote HTTP transport with a per-installation bearer key."""

    async def dispatch(self, request, call_next):
        # The health endpoint exposes no account or tool data.
        if request.url.path == "/health":
            return JSONResponse({"status": "ok", "service": "RAVICOM Mail for Yandex"})
        expected = os.getenv("MCP_BEARER_TOKEN", "").strip()
        supplied = request.headers.get("authorization", "")
        if not expected:
            return JSONResponse({"error": "HTTP transport is not configured securely"}, status_code=503)
        if not supplied.startswith("Bearer ") or not hmac.compare_digest(supplied[7:], expected):
            return JSONResponse(
                {"error": "Unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="ravicom-yandex-mail"'},
            )
        return await call_next(request)


mcp = FastMCP("RAVICOM Mail for Yandex")


def create_http_app():
    """Create the protected Streamable HTTP ASGI app used by ChatGPT."""
    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuthMiddleware)
    return app

def _connection():
    return mail.connect(os.getenv("YANDEX_IMAP_HOST", "imap.yandex.ru"), int(os.getenv("YANDEX_IMAP_PORT", "993")))

def _run(fn):
    client = _connection()
    try: return fn(client)
    finally: client.logout()

@mcp.tool()
def list_folders() -> list[dict]:
    """List mailbox folders and IMAP flags."""
    return _run(mail.folders)

@mcp.tool()
def mailbox_stats() -> dict:
    """Return mailbox folder, message, and unread counts."""
    def read(c):
        result=[]
        for f in mail.folders(c):
            try:
                typ,data=c.select(f["name"],readonly=True)
                if typ!="OK": continue
                total=int(data[0]); typ,unseen=c.search(None,"UNSEEN")
                unread=len(unseen[0].split()) if typ=="OK" and unseen and unseen[0] else 0
                result.append({"folder":f["name"],"total":total,"unread":unread})
            except Exception: continue
        return {"folders":result,"total":sum(x["total"] for x in result),"unread":sum(x["unread"] for x in result)}
    return _run(read)

@mcp.tool()
def search_mail(folder:str="INBOX",from_addr:str|None=None,subject:str|None=None,since:str|None=None,before:str|None=None,unread:bool|None=None,limit:int=50)->list[dict]:
    """Search by folder, sender, subject, IMAP dates (DD-Mon-YYYY), and read state."""
    return _run(lambda c:mail.search(c,folder,from_addr,subject,since,before,unread,limit))

@mcp.tool()
def read_message(folder:str,uid:str)->dict:
    """Read one message by IMAP UID and folder."""
    return _run(lambda c:mail.read_message(c,folder,uid))

@mcp.tool()
def mark_read(folder:str,uids:list[str])->dict:
    """Mark messages as read."""
    return _run(lambda c:mail.set_read(c,folder,uids,True))

@mcp.tool()
def mark_unread(folder:str,uids:list[str])->dict:
    """Mark messages as unread."""
    return _run(lambda c:mail.set_read(c,folder,uids,False))

@mcp.tool()
def move_messages(source_folder:str,destination_folder:str,uids:list[str])->dict:
    """Move messages between folders."""
    return _run(lambda c:mail.move(c,source_folder,destination_folder,uids))

@mcp.tool()
def cleanup_preview(folder:str="INBOX",older_than_days:int=365,limit:int=500)->dict:
    """Preview old read messages for moving to Trash. No mailbox changes."""
    if older_than_days<30: raise ValueError("older_than_days must be at least 30")
    before=(datetime.now(timezone.utc)-timedelta(days=older_than_days)).strftime("%d-%b-%Y")
    messages=_run(lambda c:mail.search(c,folder,before=before,unread=False,limit=min(limit,500)))
    preview_id=hashlib.sha256(json.dumps([folder,before,[m["uid"] for m in messages]]).encode()).hexdigest()[:16]
    PREVIEWS[preview_id]={"folder":folder,"uids":[m["uid"] for m in messages],"created":time.time()}
    return {"preview_id":preview_id,"folder":folder,"count":len(messages),"messages":messages,"expires_in_seconds":900}

@mcp.tool()
def execute_cleanup(preview_id:str,confirmation:str)->dict:
    """Move a prior preview to Trash; confirmation must be exactly MOVE TO TRASH."""
    if confirmation!="MOVE TO TRASH": raise ValueError("Explicit confirmation required: MOVE TO TRASH")
    plan=PREVIEWS.pop(preview_id,None)
    if not plan or time.time()-plan["created"]>900: raise ValueError("Preview missing or expired; create a new preview")
    return _run(lambda c:mail.move(c,plan["folder"],"Trash",plan["uids"])) if plan["uids"] else {"moved":0,"to":"Trash"}

def main():
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    if transport == "streamable-http":
        import uvicorn
        uvicorn.run(create_http_app(), host=os.getenv("MCP_HOST", "127.0.0.1"), port=int(os.getenv("MCP_PORT", "8000")))
    else:
        mcp.run(transport="stdio")
if __name__=="__main__": main()
