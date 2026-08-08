# HOL Blocking solution

To solve the HOL blocking problem, we can implement a frame generator that breaks down the response data into smaller chunks and sends them to a multi-threaded worker queue to process non-blocking operations. This way, the client can start receiving data as soon as the first chunk is available, rather than waiting for the entire response to be ready.

# Note
the web server and proxy server are 2 separate python files. The web server is a simple HTTP server that serves static files from a directory(Step 1 - Step 3). The proxy server is a multi-threaded HTTP proxy that forwards requests to the web server and caches the responses (Step 4 - Step 5).