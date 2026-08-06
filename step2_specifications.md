# Step Two: Status Code Specifications

Server supports `HTTP/1.0` and `HTTP/1.1` only. Method for these cases: **GET**.  
Forbidden paths: anything under `/secret/`, or path traversal outside the document root.

Checks run in order: **505 → 403 → 404 → 304 → 200**.

---

## 200 OK

| | |
|--|--|
| **When** | File exists, path allowed, version supported, conditional headers do not match |
| **Caused by** | Request-Line path maps to an existing file (e.g. `/test.html`) |
| **Logic** | Read file; return body with `ETag` and `Last-Modified` |
| **Test** | |

```http
GET /test.html HTTP/1.1
Host: localhost:18080

```

---

## 304 Not Modified

| | |
|--|--|
| **When** | Same as 200, but client cache is still valid |
| **Caused by** | Header `If-None-Match` matches current `ETag`, or `If-Modified-Since` ≥ file mtime |
| **Logic** | Compare validators; if match, return 304 with **no body** |
| **Test** | (use ETag from a prior 200) |

```http
GET /test.html HTTP/1.1
Host: localhost:18080
If-None-Match: 4c7c86dfc40146138520a64eaf70e849

```

---

## 403 Forbidden

| | |
|--|--|
| **When** | Path is disallowed (even if the file exists on disk) |
| **Caused by** | Request-target path under `/secret/`, or escapes document root (`..`) |
| **Logic** | Refuse access; do not serve the file |
| **Test** | |

```http
GET /secret/secret.html HTTP/1.1
Host: localhost:18080

```

---

## 404 Not Found

| | |
|--|--|
| **When** | Path is allowed but no such file |
| **Caused by** | Request-Line path (e.g. `/missing.html`) |
| **Logic** | File lookup fails → 404 HTML page |
| **Test** | |

```http
GET /missing.html HTTP/1.1
Host: localhost:18080

```

---

## 505 HTTP Version Not Supported

| | |
|--|--|
| **When** | HTTP version is not 1.0 or 1.1 |
| **Caused by** | Request-Line version token (e.g. `HTTP/2.0`) |
| **Logic** | Checked first; respond 505 without opening any file |
| **Test** | |

```http
GET /test.html HTTP/2.0
Host: localhost:18080

```
