"""IMAP XOAUTH2 operations."""
import os, imaplib, email, re, hashlib
from email.header import decode_header, make_header
from .oauth import access_token

class MailError(RuntimeError): pass

def _auth_string(user, token): return f"user={user}\x01auth=Bearer {token}\x01\x01".encode()

def connect(host="imap.yandex.ru", port=993, user=None, token=None):
    user=user or os.getenv("YANDEX_EMAIL", "")
    if not user: raise MailError("Set YANDEX_EMAIL to the mailbox address")
    client=imaplib.IMAP4_SSL(host,port)
    client.authenticate("XOAUTH2",lambda _: _auth_string(user,token or access_token()))
    return client

def folders(client):
    typ,rows=client.list()
    if typ!="OK": raise MailError("Could not list folders")
    result=[]
    for row in rows or []:
        text=row.decode("utf-8","replace")
        m=re.search(r'\((.*?)\)\s+"([^"]*)"\s+(.+)$',text)
        if m: result.append({"name":m.group(3).strip('"'),"flags":m.group(1).split(),"delimiter":m.group(2)})
    return result

def create_folder(client, folder):
    """Create a mailbox folder and return its name."""
    folder = str(folder or "").strip()
    if not folder or len(folder) > 120:
        raise MailError("Folder name must be between 1 and 120 characters")
    typ, _ = client.create(folder)
    if typ != "OK":
        raise MailError(f"Could not create folder {folder}")
    return {"created": True, "folder": folder}

def _select(client,folder):
    typ,data=client.select(folder,readonly=False)
    if typ!="OK": raise MailError(f"Cannot select folder {folder}")

def search(client,folder="INBOX",from_addr=None,subject=None,since=None,before=None,unread=None,limit=50):
    _select(client,folder); criteria=[]
    for key,value in (("FROM",from_addr),("SUBJECT",subject),("SINCE",since),("BEFORE",before)):
        if value: criteria.extend((key,f'"{value}"'))
    if unread is True: criteria.append("UNSEEN")
    elif unread is False: criteria.append("SEEN")
    if not criteria: criteria=["ALL"]
    typ,data=client.search(None,*criteria)
    if typ!="OK": raise MailError("Search failed")
    ids=(data[0].split() if data and data[0] else [])[-max(1,min(limit,200)):]
    return [summary(client,folder,uid.decode()) for uid in reversed(ids)]

def summary(client,folder,uid):
    typ,data=client.fetch(uid,"(RFC822.HEADER FLAGS)")
    if typ!="OK": raise MailError(f"Cannot fetch message {uid}")
    msg=email.message_from_bytes(data[0][1]); decode=lambda x:str(make_header(decode_header(x or "")))
    return {"uid":uid,"folder":folder,"subject":decode(msg.get("Subject")),"from":decode(msg.get("From")),"date":msg.get("Date"),"flags":data[0][0].decode(errors="replace")}

def read_message(client,folder,uid):
    _select(client,folder); typ,data=client.fetch(str(uid),"(RFC822)")
    if typ!="OK": raise MailError(f"Cannot read message {uid}")
    raw = data[0][1]
    msg=email.message_from_bytes(raw); out={k:str(make_header(decode_header(msg.get(k,"")))) for k in ("Subject","From","To","Date","Message-ID","Reply-To","Return-Path","Authentication-Results")}; parts=[]; attachments=[]
    for part in msg.walk():
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename or (part.get_content_disposition() == "attachment"):
            attachments.append({"filename": str(make_header(decode_header(filename or ""))), "content_type": part.get_content_type(), "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
        if part.get_content_type()=="text/plain" and not part.get_filename():
            if payload: parts.append(payload.decode(part.get_content_charset() or "utf-8",errors="replace"))
    out["text"]="\n".join(parts)[:30000]; out["attachments"] = attachments; return out

def set_read(client,folder,uids,read=True):
    _select(client,folder); typ,_=client.store(",".join(map(str,uids)),"+FLAGS" if read else "-FLAGS","\\Seen")
    if typ!="OK": raise MailError("Could not update read state")
    return {"updated":len(uids),"read":read}

def move(client,source,destination,uids):
    _select(client,source); ids=",".join(map(str,uids)); typ,_=client.copy(ids,destination)
    if typ!="OK": raise MailError("Could not copy messages to destination")
    client.store(ids,"+FLAGS","\\Deleted"); client.expunge()
    return {"moved":len(uids),"from":source,"to":destination}
