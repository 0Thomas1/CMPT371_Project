# Step Two & Three Report

**Server:** `http://127.0.0.1:18080` · **Code:** `server.py`

## Step Two

See `step2_specifications.md` (status-code specs and test requests).

---

## Step Three (a)

Minimal web server in `server.py`: listen with sockets → parse HTTP → return 200/304/403/404/505 per Step Two.

---

## Step Three (b)

Open browser: `http://127.0.0.1:18080/test.html`  
Result: page shows *Congratulations! Your Web Server is Working!*

3b

---

## Step Three (c)

### 200 OK

```powershell
curl.exe -i http://127.0.0.1:18080/test.html
```

Result: `HTTP/1.1 200 OK`

200

### 304 Not Modified

```powershell
curl.exe -i -H "If-None-Match: <etag-from-200>" http://127.0.0.1:18080/test.html
```

Result: `HTTP/1.1 304 Not Modified`

304

### 403 Forbidden

```powershell
curl.exe -i http://127.0.0.1:18080/secret/secret.html
```

Result: `HTTP/1.1 403 Forbidden`

403

### 404 Not Found

```powershell
curl.exe -i http://127.0.0.1:18080/missing.html
```

Result: `HTTP/1.1 404 Not Found`

404

### 505 HTTP Version Not Supported

```powershell
python -c "import socket; s=socket.create_connection(('127.0.0.1',18080)); s.sendall(b'GET /test.html HTTP/2.0\r\nHost: localhost\r\nConnection: close\r\n\r\n'); print(s.recv(4096).decode()); s.close()"
```

Result: `HTTP/1.1 505 HTTP Version Not Supported`

505