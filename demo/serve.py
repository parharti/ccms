"""Serves the demo resume links on http://127.0.0.1:8766 (run make_demo_data.py first)."""

import functools
import http.server
import os

HERE = os.path.dirname(os.path.abspath(__file__))
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=os.path.join(HERE, "files"))

if __name__ == "__main__":
    with http.server.ThreadingHTTPServer(("127.0.0.1", 8766), handler) as server:
        print("Serving demo resumes on http://127.0.0.1:8766  (Ctrl+C to stop)")
        server.serve_forever()
