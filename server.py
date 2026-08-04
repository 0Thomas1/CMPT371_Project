from socket import *
from urllib.parse import urlparse,parse_qs


HOST = 'localhost'
PORT = 8080
INDEX_PATH = 'test.html'
CURRENT_VERSION = 'v1'
#define HTTP responses
def http_response(status_code, body):
    status_messages = {
        200: 'OK',
        304: 'Not Modified',
        403: 'Forbidden',
        404: 'Not Found',
        505: 'HTTP Version Not Supported'
    }
    status_message = status_messages.get(status_code, 'Unknown Status')
    response = f"HTTP/1.1 {status_code} {status_message}\r\n"
    response += "Content-Type: text/html\r\n"
    response += f"Content-Length: {len(body)}\r\n"
    response += "\r\n"
    response += body
    return response

server_socket = socket(AF_INET, SOCK_STREAM)
server_socket.bind((HOST, PORT))
server_socket.listen(1)
print(f"Server is running on http://{HOST}:{PORT}")

while True:
    client_socket, addr = server_socket.accept()
    print(f"Connection from {addr}")

    request = client_socket.recv(1024).decode('utf-8')
    print(f"Request:\n{request}")

    # Parse the HTTP request
    request_lines = request.splitlines()
    if len(request_lines) > 0:
        request_line = request_lines[0]
        method, path, version = request_line.split()

        
        # Handle GET requests
        if method == 'GET':
            parsed_url = urlparse(path)
            query_params = parse_qs(parsed_url.query)

            # Example: Handle a specific path
            if parsed_url.path == '/':
                body = "<html><body><h1>Welcome to the Home Page</h1></body></html>"
                response = http_response(200, body)
            if parsed_url.path == '/test.html':
                with open(INDEX_PATH, 'r') as f:
                    body = f.read()
                response = http_response(200, body)
            else:
                body = "<html><body><h1>404 Not Found</h1></body></html>"
                response = http_response(404, body)
        else:
            body = "<html><body><h1>405 Method Not Allowed</h1></body></html>"
            response = http_response(405, body)

        client_socket.sendall(response.encode('utf-8'))
    client_socket.close()