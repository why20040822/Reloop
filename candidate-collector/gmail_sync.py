from __future__ import annotations

import argparse
import email
import fcntl
import hashlib
import imaplib
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from contextlib import closing
from email.header import decode_header
from email.message import Message
from pathlib import Path
from typing import Any

import fitz


ROOT = Path(__file__).resolve().parent
DOWNLOAD_DIR = ROOT / "data" / "gmail-attachments"
STATE_PATH = ROOT / "data" / "gmail-state.json"
LOCK_PATH = ROOT / "data" / "gmail-sync.lock"
DB_PATH = ROOT / "data" / "candidates.db"
KEYCHAIN_ACCOUNT = "ttc-candidate-collector"
EMAIL_SERVICE = "TTC_GMAIL_EMAIL"
PASSWORD_SERVICE = "TTC_GMAIL_APP_PASSWORD"
API_BASE = "http://127.0.0.1:8765"
DEFAULT_QUERY = (
    "after:2026/07/06 has:attachment "
    "{filename:pdf filename:doc filename:docx filename:png filename:jpg filename:jpeg}"
)
RESUME_TERMS = re.compile(
    r"(简历|应聘|候选|人选|求职|人才|面试|推荐|resume|\bcv\b|candidate|application|curriculum)",
    re.I,
)
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".tiff"}
SYNC_LOCK = threading.Lock()
LAST_STATUS: dict[str, Any] = {
    "state": "not_started",
    "message": "尚未同步",
    "downloaded": 0,
    "imported": 0,
    "skipped": 0,
    "errors": [],
}


class EmailSyncConfig:
    """Runtime configuration for email resume sync.

    Credentials are never stored in this object as plaintext.  For Gmail the
    keychain is used; for generic IMAP the caller must provide a password
    retrieval function or use environment variables at runtime.
    """

    def __init__(self, **kwargs: Any):
        self.imap_server = kwargs.get("imap_server", "imap.gmail.com")
        self.imap_port = int(kwargs.get("imap_port", 993))
        self.imap_ssl = bool(kwargs.get("imap_ssl", True))
        self.username = kwargs.get("username", "")
        self.password = kwargs.get("password", "")
        self.use_keychain = bool(kwargs.get("use_keychain", False))
        self.query = kwargs.get("query", DEFAULT_QUERY)
        self.resume_terms = kwargs.get("resume_terms", RESUME_TERMS)
        self.allowed_extensions = set(kwargs.get("allowed_extensions", ALLOWED_EXTENSIONS))
        self.max_email_size_mb = int(kwargs.get("max_email_size_mb", 16))
        self.max_file_size_mb = int(kwargs.get("max_file_size_mb", 12))
        self.watch_interval_seconds = int(kwargs.get("watch_interval_seconds", 300))
        self.api_base = kwargs.get("api_base", API_BASE)
        self.keychain_account = kwargs.get("keychain_account", KEYCHAIN_ACCOUNT)
        self.email_service = kwargs.get("email_service", EMAIL_SERVICE)
        self.password_service = kwargs.get("password_service", PASSWORD_SERVICE)

    @classmethod
    def from_env(cls) -> "EmailSyncConfig":
        """Load configuration from environment variables.

        Expected variables:
          TTC_EMAIL_IMAP_SERVER   default imap.gmail.com
          TTC_EMAIL_IMAP_PORT     default 993
          TTC_EMAIL_IMAP_SSL      default true
          TTC_EMAIL_USERNAME
          TTC_EMAIL_PASSWORD      (only when not using keychain)
          TTC_EMAIL_QUERY         Gmail-style search query or IMAP criteria
          TTC_EMAIL_USE_KEYCHAIN  true/false; default false
          TTC_EMAIL_SYNC_INTERVAL seconds; default 300
        """
        return cls(
            imap_server=os.getenv("TTC_EMAIL_IMAP_SERVER", "imap.gmail.com"),
            imap_port=int(os.getenv("TTC_EMAIL_IMAP_PORT", "993")),
            imap_ssl=os.getenv("TTC_EMAIL_IMAP_SSL", "true").lower() in ("1", "true", "yes"),
            username=os.getenv("TTC_EMAIL_USERNAME", ""),
            password=os.getenv("TTC_EMAIL_PASSWORD", ""),
            use_keychain=os.getenv("TTC_EMAIL_USE_KEYCHAIN", "false").lower() in ("1", "true", "yes"),
            query=os.getenv("TTC_EMAIL_QUERY", DEFAULT_QUERY),
            watch_interval_seconds=int(os.getenv("TTC_EMAIL_SYNC_INTERVAL", "300")),
        )

    @classmethod
    def for_gmail(cls) -> "EmailSyncConfig":
        """Gmail-specific config using macOS keychain for credentials."""
        return cls(
            imap_server="imap.gmail.com",
            imap_port=993,
            imap_ssl=True,
            use_keychain=True,
            query=DEFAULT_QUERY,
        )


def keychain_get(service: str, account: str = KEYCHAIN_ACCOUNT) -> str:
    try:
        result = subprocess.run(
            [
                "security", "find-generic-password",
                "-a", account, "-s", service, "-w",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("邮箱尚未配置，请先运行 gmail_setup.py 或设置 TTC_EMAIL_USERNAME/PASSWORD") from exc
    return result.stdout.strip()


def _resolve_credentials(config: EmailSyncConfig) -> tuple[str, str]:
    if config.use_keychain:
        username = keychain_get(config.email_service, config.keychain_account)
        password = keychain_get(config.password_service, config.keychain_account)
        return username, password
    if not config.username or not config.password:
        raise RuntimeError("邮箱用户名或密码未配置")
    return config.username, config.password


def decode_text_header(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for part, charset in decode_header(value):
        if isinstance(part, bytes):
            parts.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(part)
    return "".join(parts)


def safe_filename(value: str) -> str:
    value = decode_text_header(value)
    value = value.replace("\\", "_").replace("/", "_").replace("\x00", "")
    while ".." in value:
        value = value.replace("..", "_")
    value = re.sub(r"[\r\n\t]+", " ", value).strip(" .")
    value = re.sub(r"\s+", " ", value)
    return value[:150] or "attachment"


def extract_word_text(path: Path) -> str:
    try:
        result = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(path)],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    return result.stdout.decode("utf-8", errors="replace").strip()


def no_proxy_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def import_attachment(path: Path, source_url: str, config: EmailSyncConfig) -> dict[str, Any]:
    opener = no_proxy_opener()
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        url = config.api_base + "/api/import-file?" + urllib.parse.urlencode({
            "filename": path.name,
            "platform": "Email",
            "source_type": "email_imap_attachment",
            "source_url": source_url,
        })
        request = urllib.request.Request(
            url,
            data=path.read_bytes(),
            headers={"Content-Type": "application/pdf"},
            method="POST",
        )
    else:
        text = extract_word_text(path)
        if len(text) < 20:
            raise RuntimeError("Word 文件没有提取到足够文字")
        body = json.dumps({
            "text": text,
            "title": path.name,
            "url": source_url,
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            config.api_base + "/api/import-text",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    with opener.open(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def message_bytes(fetch_result: list[Any]) -> bytes:
    for item in fetch_result:
        if isinstance(item, tuple) and isinstance(item[1], bytes):
            return item[1]
    return b""


def attachment_parts(message: Message, allowed_extensions: set[str]):
    for part in message.walk():
        filename = part.get_filename()
        if not filename:
            continue
        name = safe_filename(filename)
        if Path(name).suffix.lower() not in allowed_extensions:
            continue
        payload = part.get_payload(decode=True)
        if payload:
            yield name, payload


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"attachment_hashes": [], "message_ids": []}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"attachment_hashes": [], "message_ids": []}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_PATH.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(STATE_PATH)


def _init_retry_db() -> None:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS email_sync_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT NOT NULL UNIQUE,
                subject TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                retry_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_email_queue_status ON email_sync_queue(status)"
        )
        conn.commit()


def _queue_message(message_id: str, subject: str, status: str = "pending", error: str = "") -> None:
    _init_retry_db()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            INSERT INTO email_sync_queue (message_id, subject, status, retry_count, error_message, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                status=excluded.status,
                retry_count=email_sync_queue.retry_count + 1,
                error_message=excluded.error_message,
                updated_at=excluded.updated_at
            """,
            (message_id, subject, status, 0, error, now, now),
        )
        conn.commit()


def _is_scanned_resume(subject: str, filename: str, payload: bytes, config: EmailSyncConfig) -> bool:
    """Determine whether an attachment is likely a resume.

    Does not use role-specific keywords; any PDF with resume-like text is kept.
    """
    search_text = subject + " " + filename
    if config.resume_terms.search(search_text):
        return True
    if Path(filename).suffix.lower() == ".pdf":
        try:
            document = fitz.open(stream=payload, filetype="pdf")
            extracted = "\n".join(page.get_text("text") for page in list(document)[:2])
            return bool(config.resume_terms.search(extracted[:20000]))
        except Exception:
            return False
    return False


def _imap_connect(config: EmailSyncConfig) -> imaplib.IMAP4_SSL | imaplib.IMAP4:
    username, password = _resolve_credentials(config)
    if config.imap_ssl:
        connection = imaplib.IMAP4_SSL(config.imap_server, config.imap_port, timeout=30)
    else:
        connection = imaplib.IMAP4(config.imap_server, config.imap_port, timeout=30)
    connection.login(username, password)
    return connection


def _search_uids(connection: imaplib.IMAP4_SSL | imaplib.IMAP4, query: str, limit: int) -> list[bytes]:
    """Execute a search query. Supports Gmail X-GM-RAW or standard IMAP criteria."""
    if "imap.gmail.com" in connection.host.lower() and "X-GM-RAW" in str(connection.capability()):
        result, data = connection.uid("SEARCH", None, "X-GM-RAW", f'"{query}"')
    else:
        # Fallback to standard IMAP search: use UNSEEN with resume terms or all recent.
        # Most generic IMAP servers do not support complex Gmail queries.
        criteria = query if query and not query.startswith("after:") else "UNSEEN"
        result, data = connection.uid("SEARCH", None, criteria)
    if result != "OK" or not data or not data[0]:
        return []
    uids = data[0].split()
    return uids[-limit:]


def sync_email(config: EmailSyncConfig | None = None, limit: int = 25) -> dict[str, Any]:
    """Unified IMAP email resume sync.

    Reads configuration from ``config`` or environment variables.  Downloads
    resume-like attachments, deduplicates by Message-ID + SHA-256, and imports
    them into the local candidate collector.  Per-message failures are queued
    for retry instead of aborting the whole batch.
    """
    global LAST_STATUS
    if config is None:
        config = EmailSyncConfig.from_env()

    if not SYNC_LOCK.acquire(blocking=False):
        return {**LAST_STATUS, "state": "busy", "message": "已有邮箱同步正在运行"}
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = LOCK_PATH.open("a+")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_handle.close()
        SYNC_LOCK.release()
        return {**LAST_STATUS, "state": "busy", "message": "另一个进程正在同步邮箱"}

    status: dict[str, Any] = {
        "state": "running",
        "message": "正在读取邮箱",
        "downloaded": 0,
        "imported": 0,
        "skipped": 0,
        "errors": [],
    }
    LAST_STATUS = status
    connection: imaplib.IMAP4_SSL | imaplib.IMAP4 | None = None
    try:
        connection = _imap_connect(config)
        result, _ = connection.select("INBOX", readonly=True)
        if result != "OK":
            raise RuntimeError("无法以只读方式打开收件箱")

        uids = _search_uids(connection, config.query, limit)
        state = load_state()
        known_hashes = set(state.get("attachment_hashes", []))
        known_messages = set(state.get("message_ids", []))
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

        for uid in reversed(uids):
            try:
                size_result, size_data = connection.uid("FETCH", uid, "(RFC822.SIZE)")
                size_blob = b" ".join(
                    item if isinstance(item, bytes) else item[0]
                    for item in size_data
                    if isinstance(item, (bytes, tuple))
                )
                size_match = re.search(rb"RFC822\.SIZE\s+(\d+)", size_blob)
                if size_result == "OK" and size_match and int(size_match.group(1)) > config.max_email_size_mb * 1024 * 1024:
                    status["skipped"] += 1
                    status["errors"].append("跳过超过%dMB的邮件 UID " % config.max_email_size_mb + uid.decode(errors="ignore"))
                    continue

                result, fetched = connection.uid("FETCH", uid, "(BODY.PEEK[])")
                if result != "OK":
                    status["errors"].append("邮件读取失败 UID " + uid.decode(errors="ignore"))
                    _queue_message(uid.decode(errors="ignore"), "", "failed", "FETCH failed")
                    continue

                raw = message_bytes(fetched)
                if not raw:
                    continue
                message = email.message_from_bytes(raw)
                message_id = (message.get("Message-ID") or uid.decode(errors="ignore")).strip()
                subject = decode_text_header(message.get("Subject"))
                source_url = "email://message/" + urllib.parse.quote(message_id, safe="")
                parts = list(attachment_parts(message, config.allowed_extensions))
                relevance_text = subject + " " + " ".join(filename for filename, _ in parts)
                if not config.resume_terms.search(relevance_text):
                    status["skipped"] += len(parts) or 1
                    continue

                target_parts = [
                    (filename, payload)
                    for filename, payload in parts
                    if _is_scanned_resume(subject, filename, payload, config)
                ]
                if not target_parts:
                    status["skipped"] += len(parts) or 1
                    continue

                found_attachment = False
                for filename, payload in target_parts:
                    found_attachment = True
                    digest = hashlib.sha256(payload).hexdigest()
                    if digest in known_hashes:
                        status["skipped"] += 1
                        continue
                    path = DOWNLOAD_DIR / (digest[:12] + "_" + filename)
                    path.write_bytes(payload)
                    status["downloaded"] += 1
                    try:
                        import_attachment(path, source_url, config)
                        status["imported"] += 1
                        known_hashes.add(digest)
                    except Exception as exc:
                        err = subject[:80] + " / " + filename + "：" + str(exc)
                        status["errors"].append(err)
                        _queue_message(message_id, subject, "failed", str(exc))
                if found_attachment:
                    known_messages.add(message_id)
                state["attachment_hashes"] = sorted(known_hashes)
                state["message_ids"] = sorted(known_messages)[-5000:]
                save_state(state)
            except Exception as exc:
                status["errors"].append(str(exc))
                _queue_message(uid.decode(errors="ignore"), "", "failed", str(exc))

        status["state"] = "completed"
        status["message"] = (
            f"同步完成：下载 {status['downloaded']}，入库 {status['imported']}，"
            f"跳过重复 {status['skipped']}，错误 {len(status['errors'])}"
        )
        return status
    except Exception as exc:
        status["state"] = "failed"
        status["message"] = str(exc)
        status["errors"].append(str(exc))
        return status
    finally:
        if connection is not None:
            try:
                connection.logout()
            except Exception:
                pass
        LAST_STATUS = status
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()
        SYNC_LOCK.release()


def sync_gmail(limit: int = 25, query: str = DEFAULT_QUERY) -> dict[str, Any]:
    """Backward-compatible Gmail sync entrypoint.

    Uses macOS keychain credentials and imap.gmail.com.  The hardcoded role
    filter has been removed; only resume-like attachments are kept.
    """
    config = EmailSyncConfig.for_gmail()
    config.query = query
    return sync_email(config, limit=limit)


def watch_loop(interval_seconds: int = 300) -> None:
    time.sleep(10)
    while True:
        sync_email()
        time.sleep(max(60, interval_seconds))


def start_watcher(interval_seconds: int = 300) -> threading.Thread:
    thread = threading.Thread(
        target=watch_loop,
        args=(interval_seconds,),
        name="email-resume-sync",
        daemon=True,
    )
    thread.start()
    return thread


def main() -> int:
    parser = argparse.ArgumentParser(description="只读同步邮箱简历附件")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--config", help="Path to JSON config file")
    args = parser.parse_args()

    if args.config:
        config = EmailSyncConfig(**json.loads(Path(args.config).read_text(encoding="utf-8")))
    else:
        config = EmailSyncConfig.from_env()
        # Backward compat: if Gmail keychain is configured, prefer it.
        try:
            keychain_get(EMAIL_SERVICE)
            config = EmailSyncConfig.for_gmail()
        except RuntimeError:
            pass
        config.query = args.query

    if args.watch:
        while True:
            result = sync_email(config, limit=args.limit)
            print(json.dumps(result, ensure_ascii=False))
            time.sleep(max(60, args.interval))
    result = sync_email(config, limit=args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["state"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
