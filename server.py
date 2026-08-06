"""Minimal HTTP/1.x web server using raw sockets (no http module)."""

from socket import *
from urllib.parse import unquote, urlparse
from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path
from hashlib import md5
from datetime import timezone
import mimetypes

HOST = "127.0.0.1"
PORT = 18080  # use 8080 if available on your machine
DOC_ROOT = Path(__file__).resolve().parent
SUPPORTED_VERSIONS = {"HTTP/1.0", "HTTP/1.1"}
FORBIDDEN_PREFIXES = ("/secret/",)

STATUS_TEXT = {
    200: "OK",
    304: "Not Modified",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    505: "HTTP Version Not Supported",
}


def html_page(title, message):
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title></head><body><h1>{title}</h1>"
        f"<p>{message}</p></body></html>"
    )


def parse_headers(header_lines):
    headers = {}
    for line in header_lines:
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    return headers


def parse_request(raw):
    if not raw.strip():
        return None
    lines = raw.split("\r\n")
    if len(lines) == 1:
        lines = raw.split("\n")
    request_line = lines[0].strip()
    parts = request_line.split()
    if len(parts) != 3:
        return None
    method, target, version = parts
    blank = 0
    for i, line in enumerate(lines[1:], start=1):
        if line == "":
            blank = i
            break
    headers = parse_headers(lines[1:blank] if blank else lines[1:])
    return {
        "method": method.upper(),
        "target": target,
        "version": version,
        "headers": headers,
    }


def build_response(status, body=b"", extra_headers=None):
    if isinstance(body, str):
        body = body.encode("utf-8")
    if status == 304:
        body = b""
    reason = STATUS_TEXT.get(status, "Unknown")
    lines = [
        f"HTTP/1.1 {status} {reason}",
        f"Content-Length: {len(body)}",
        "Connection: close",
    ]
    extra_headers = list(extra_headers or [])
    has_content_type = any(h.lower().startswith("content-type:") for h in extra_headers)
    if body and not has_content_type:
        lines.append("Content-Type: text/html; charset=utf-8")
    lines.extend(extra_headers)
    return ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8") + body


def http_date(ts):
    return formatdate(timeval=ts, localtime=False, usegmt=True)


def file_etag(data):
    return '"' + md5(data).hexdigest() + '"'


def resolve_path(url_path):
    """Map request path to a file under DOC_ROOT. Returns (kind, path_or_none).

    kind: 'forbidden' | 'not_found' | 'ok'
    """
    parsed = urlparse(url_path)
    path = unquote(parsed.path)

    if path in ("", "/"):
        path = "/test.html"

    # Forbidden by policy prefix (check before filesystem)
    for prefix in FORBIDDEN_PREFIXES:
        if path == prefix.rstrip("/") or path.startswith(prefix):
            return "forbidden", None

    # Normalize and block path traversal outside document root
    relative = path.lstrip("/")
    candidate = (DOC_ROOT / relative).resolve()
    try:
        candidate.relative_to(DOC_ROOT)
    except ValueError:
        return "forbidden", None

    if not candidate.is_file():
        return "not_found", None
    return "ok", candidate


def normalize_etag(tag):
    tag = tag.strip()
    if tag.startswith("W/"):
        tag = tag[2:].strip()
    if len(tag) >= 2 and tag[0] == tag[-1] == '"':
        tag = tag[1:-1]
    return tag


def validators_match(headers, etag, last_modified_ts):
    current = normalize_etag(etag)
    inm = headers.get("if-none-match")
    if inm:
        tags = [normalize_etag(t) for t in inm.split(",")]
        if "*" in tags or current in tags:
            return True

    ims = headers.get("if-modified-since")
    if ims:
        try:
            since = parsedate_to_datetime(ims)
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            mtime = datetime_from_ts(last_modified_ts)
            # Resource not modified if mtime <= If-Modified-Since
            if mtime <= since:
                return True
        except (TypeError, ValueError, IndexError, OverflowError):
            pass
    return False


def datetime_from_ts(ts):
    from datetime import datetime

    return datetime.fromtimestamp(ts, tz=timezone.utc)


def handle_get(target, headers):
    kind, path = resolve_path(target)
    if kind == "forbidden":
        body = html_page("403 Forbidden", "You are not allowed to access this resource.")
        return build_response(403, body)
    if kind == "not_found":
        body = html_page("404 Not Found", f"The requested URL {target} was not found.")
        return build_response(404, body)

    data = path.read_bytes()
    mtime = path.stat().st_mtime
    etag = file_etag(data)
    last_mod = http_date(mtime)
    ctype, _ = mimetypes.guess_type(str(path))
    if not ctype:
        ctype = "application/octet-stream"
    if ctype.startswith("text/"):
        ctype = ctype + "; charset=utf-8"

    extra = [
        f"Content-Type: {ctype}",
        f"ETag: {etag}",
        f"Last-Modified: {last_mod}",
    ]

    if validators_match(headers, etag, mtime):
        return build_response(304, b"", extra_headers=extra)

    return build_response(200, data, extra_headers=extra)


def handle_client(client_socket, addr):
    try:
        raw = client_socket.recv(65536).decode("utf-8", errors="replace")
        print(f"Connection from {addr}")
        print(f"Request:\n{raw}")

        req = parse_request(raw)
        if req is None:
            client_socket.sendall(
                build_response(404, html_page("404 Not Found", "Malformed request."))
            )
            return

        # 505: check HTTP-version first
        if req["version"] not in SUPPORTED_VERSIONS:
            response = build_response(
                505,
                html_page(
                    "505 HTTP Version Not Supported",
                    f"Version {req['version']} is not supported. Use HTTP/1.0 or HTTP/1.1.",
                ),
            )
            client_socket.sendall(response)
            return

        if req["method"] != "GET":
            response = build_response(
                405,
                html_page("405 Method Not Allowed", "Only GET is supported."),
            )
            client_socket.sendall(response)
            return

        response = handle_get(req["target"], req["headers"])
        client_socket.sendall(response)
    finally:
        client_socket.close()


def main():
    server_socket = socket(AF_INET, SOCK_STREAM)
    server_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen(5)
    print(f"Server is running on http://{HOST}:{PORT}", flush=True)
    print(f"Document root: {DOC_ROOT}", flush=True)

    try:
        while True:
            client_socket, addr = server_socket.accept()
            handle_client(client_socket, addr)
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server_socket.close()


if __name__ == "__main__":
    main()
