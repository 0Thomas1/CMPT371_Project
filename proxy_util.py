"""Helpers for a minimal HTTP proxy server."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from socket import AF_INET, SOCK_STREAM, SOL_SOCKET, SO_REUSEADDR, create_connection, socket
import threading
from urllib.parse import urlparse
from pathlib import Path
import time
CACHE_MAX_AGE_SECONDS = 300


PROXY_NAME = "proxy-server"
SUPPORTED_VERSIONS = {"HTTP/1.0", "HTTP/1.1"}
REQUEST_CHUNK_SIZE = 65536
CACHE_DIR = "cached_page"
BAD_REQUEST_TITLE = "400 Bad Request"

DOC_ROOT = Path(__file__).resolve().parent
CACHE_ROOT = DOC_ROOT / CACHE_DIR

@dataclass
class HttpRequest:
	method: str
	target: str
	version: str
	headers: list[tuple[str, str]]
	body: bytes = b""


def html_page(title: str, message: str) -> str:
	return (
		"<!DOCTYPE html><html><head><meta charset='utf-8'>"
		f"<title>{title}</title></head><body><h1>{title}</h1>"
		f"<p>{message}</p></body></html>"
	)


STATUS_TEXT = {
	400: "Bad Request",
	200: "OK",
	403: "Forbidden",
	405: "Method Not Allowed",
	500: "Internal Server Error",
	502: "Bad Gateway",
	505: "HTTP Version Not Supported",
}


def build_response(status: int, body: str | bytes = b"", extra_headers: list[str] | None = None) -> bytes:
	if isinstance(body, str):
		body = body.encode("utf-8")
	reason = STATUS_TEXT.get(status, "Unknown")
	headers = [
		f"HTTP/1.1 {status} {reason}",
		f"Content-Length: {len(body)}",
		"Connection: close",
	]
	extra_headers = list(extra_headers or [])
	has_content_type = any(header.lower().startswith("content-type:") for header in extra_headers)
	if body and not has_content_type:
		headers.append("Content-Type: text/html; charset=utf-8")
	headers.extend(extra_headers)
	return ("\r\n".join(headers) + "\r\n\r\n").encode("utf-8") + body


def read_http_message(client_socket) -> bytes:
	data = bytearray()
	while True:
		chunk = client_socket.recv(REQUEST_CHUNK_SIZE)
		if not chunk:
			break
		data.extend(chunk)
		if b"\r\n\r\n" in data or b"\n\n" in data:
			break
		if len(data) > 1024 * 1024:
			raise ValueError("request too large")
	return bytes(data)


def parse_request(raw_request: bytes) -> HttpRequest | None:
	if not raw_request.strip():
		return None

	text = raw_request.decode("latin-1", errors="replace")
	if "\r\n\r\n" in text:
		head, _ = text.split("\r\n\r\n", 1)
		delimiter = b"\r\n\r\n"
	elif "\n\n" in text:
		head, _ = text.split("\n\n", 1)
		delimiter = b"\n\n"
	else:
		return None

	head_lines = head.split("\r\n") if "\r\n" in head else head.split("\n")
	request_line = head_lines[0].strip()
	parts = request_line.split()
	if len(parts) != 3:
		return None

	method, target, version = parts
	headers: list[tuple[str, str]] = []
	for line in head_lines[1:]:
		if not line or ":" not in line:
			continue
		name, value = line.split(":", 1)
		headers.append((name.strip(), value.strip()))

	body_bytes = raw_request.split(delimiter, 1)[1] if delimiter in raw_request else b""
	return HttpRequest(method=method.upper(), target=target, version=version, headers=headers, body=body_bytes)


def parse_absolute_target(target: str) -> tuple[str, int, str]:
	parsed = urlparse(target)
	if parsed.scheme != "http" or not parsed.hostname:
		raise ValueError("proxy requires an absolute http:// URI")

	port = parsed.port or 80
	path = parsed.path or "/"
	if parsed.params:
		path += ";" + parsed.params
	if parsed.query:
		path += "?" + parsed.query
	return parsed.hostname, port, path


def normalize_cache_key(target: str) -> str:
	parsed = urlparse(target)
	if parsed.scheme != "http" or not parsed.hostname:
		raise ValueError("proxy requires an absolute http:// URI")

	host = parsed.hostname.lower()
	port = parsed.port
	if port and port != 80:
		host = f"{host}:{port}"
	path = parsed.path or "/"
	if parsed.params:
		path += ";" + parsed.params
	if parsed.query:
		path += "?" + parsed.query
	return f"http://{host}{path}"


def cache_file_for_target(target: str) -> Path | None:
	try:
		cache_key = normalize_cache_key(target)
	except ValueError:
		return None

	cache_name = sha256(cache_key.encode("utf-8")).hexdigest() + ".cache"
	return CACHE_ROOT / cache_name


def cache_path_for_target(target: str) -> Path | None:
	path = cache_file_for_target(target)
	if path is None or not path.is_file():
		return None
	return path


def cache_is_stale(path: Path) -> bool:
	try:
		age = time.time() - path.stat().st_mtime
	except OSError:
		return True
	return age > CACHE_MAX_AGE_SECONDS


def extract_response_body(response_data: bytes) -> bytes:
	for delimiter in (b"\r\n\r\n", b"\n\n"):
		if delimiter in response_data:
			return response_data.split(delimiter, 1)[1]
	return response_data


def fetch_and_cache_response(target: str) -> bytes | None:
	try:
		host, port, path = parse_absolute_target(target)
	except ValueError:
		return None

	request_line = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
	try:
		with create_connection((host, port), timeout=10) as upstream_socket:
			upstream_socket.sendall(request_line.encode("utf-8"))
			response_data = bytearray()
			while True:
				chunk = upstream_socket.recv(REQUEST_CHUNK_SIZE)
				if not chunk:
					break
				response_data.extend(chunk)
	except OSError as exc:
		print(f"Failed to fetch {target}: {exc}")
		return None

	raw_response = bytes(response_data)
	path = cache_file_for_target(target)
	if path is not None:
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_bytes(raw_response)
		print(f"Cached response for {target} at {path}")
	return raw_response


def serve_cached_response(target: str, client_socket) -> bool:
	path = cache_path_for_target(target)
	if path is None:
		return False

	raw_response = path.read_bytes()
	if cache_is_stale(path):
		refreshed_response = fetch_and_cache_response(target)
		if refreshed_response is not None:
			raw_response = refreshed_response

	print(f"Serving cached response for {target} from {path}")
	client_socket.sendall(raw_response)
	return True


def header_value(headers: list[tuple[str, str]], name: str) -> str | None:
	lowered = name.lower()
	for header_name, value in headers:
		if header_name.lower() == lowered:
			return value
	return None


def set_header(headers: list[tuple[str, str]], name: str, value: str) -> list[tuple[str, str]]:
	lowered = name.lower()
	updated: list[tuple[str, str]] = []
	replaced = False
	for header_name, header_value in headers:
		if header_name.lower() == lowered:
			if not replaced:
				updated.append((name, value))
				replaced = True
			continue
		updated.append((header_name, header_value))
	if not replaced:
		updated.append((name, value))
	return updated


def append_via_header(headers: list[tuple[str, str]], version: str) -> list[tuple[str, str]]:
	via_value = f"{version.split('/', 1)[1]} {PROXY_NAME}"
	current = header_value(headers, "Via")
	if current:
		return set_header(headers, "Via", f"{current}, {via_value}")
	return headers + [("Via", via_value)]


def build_forward_request(request: HttpRequest) -> bytes:
	host, port, path = parse_absolute_target(request.target)
	headers = list(request.headers)

	if not header_value(headers, "Host"):
		host_header = host if port == 80 else f"{host}:{port}"
		headers = headers + [("Host", host_header)]

	headers = set_header(headers, "Connection", "close")
	headers = append_via_header(headers, request.version)

	request_line = f"{request.method} {path} {request.version}"
	header_block = "\r\n".join(f"{name}: {value}" for name, value in headers)
	return (request_line + "\r\n" + header_block + "\r\n\r\n").encode("latin-1") + request.body


def forward_request(request: HttpRequest, client_socket) -> None:
	host, port, _ = parse_absolute_target(request.target)
	upstream_request = build_forward_request(request)
	try:
		with create_connection((host, port), timeout=10) as upstream_socket:
			upstream_socket.sendall(upstream_request)
			response_data = bytearray()
			while True:
				chunk = upstream_socket.recv(REQUEST_CHUNK_SIZE)
				if not chunk:
					break
				response_data.extend(chunk)

			raw_response = bytes(response_data)
			cache_file = cache_file_for_target(request.target)
			if cache_file is not None:
				cache_file.parent.mkdir(parents=True, exist_ok=True)
				cache_file.write_bytes(raw_response)
				print(f"Cached response for {request.target} at {cache_file}")

			client_socket.sendall(raw_response)
	except OSError as exc:
		response = build_response(
			502,
			html_page("502 Bad Gateway", f"Failed to reach {host}:{port}: {exc}"),
		)
		client_socket.sendall(response)


def handle_proxy_client(client_socket, addr) -> None:
	try:
		raw_request = read_http_message(client_socket)
		print(f"Connection from {addr}")
		print(f"Request:\n{raw_request.decode('utf-8', errors='replace')}")

		request = parse_request(raw_request)
		if request is None:
			client_socket.sendall(build_response(400, html_page(BAD_REQUEST_TITLE, "Malformed request.")))
			return

		if request.version not in SUPPORTED_VERSIONS:
			client_socket.sendall(
				build_response(
					505,
					html_page(
						"505 HTTP Version Not Supported",
						f"Version {request.version} is not supported. Use HTTP/1.0 or HTTP/1.1.",
					),
				)
			)
			return

		if request.method != "GET":
			client_socket.sendall(
				build_response(405, html_page("405 Method Not Allowed", "Only GET is supported."))
			)
			return

		if serve_cached_response(request.target, client_socket):
			return

		try:
			parse_absolute_target(request.target)
		except ValueError as exc:
			client_socket.sendall(build_response(400, html_page(BAD_REQUEST_TITLE, str(exc))))
			return

		forward_request(request, client_socket)
	except ValueError as exc:
		client_socket.sendall(build_response(400, html_page(BAD_REQUEST_TITLE, str(exc))))
	except OSError as exc:
		client_socket.sendall(build_response(500, html_page("500 Internal Server Error", str(exc))))
	finally:
		client_socket.close()


def serve(host: str, port: int) -> None:
	server_socket = socket(AF_INET, SOCK_STREAM)
	server_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
	server_socket.bind((host, port))
	server_socket.listen(5)
	print(f"Proxy server is running on http://{host}:{port}", flush=True)

	try:
		while True:
			client_socket, addr = server_socket.accept()
			threading.Thread(
				target=handle_proxy_client,
				args=(client_socket, addr),
				daemon=True,
			).start()
	except KeyboardInterrupt:
		print("\nShutting down.")
	finally:
		server_socket.close()
