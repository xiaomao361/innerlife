from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from innerlife.llm import AnthropicCompatibleBackend, OpenAICompatibleBackend


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(length))
        assert body["model"] == "local-small"
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "changed": False,
                                "reason": "本地模型认为没有变化",
                                "internal_events": [],
                                "state_update": {},
                                "pending_shares": [],
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }
        encoded = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):
        return


def test_openai_compatible_local_backend():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        backend = OpenAICompatibleBackend(
            f"http://127.0.0.1:{server.server_port}/v1"
        )
        result = backend.generate(
            system_prompt="test",
            payload={"pending_inbox_events": []},
            model="local-small",
        )
        assert result["changed"] is False
    finally:
        server.shutdown()
        thread.join()


class AnthropicHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(length))
        assert body["model"] == "compatible-small"
        response = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "changed": False,
                            "reason": "兼容服务认为没有变化",
                            "internal_events": [],
                            "state_update": {},
                            "pending_shares": [],
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        }
        encoded = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):
        return


def test_anthropic_compatible_backend():
    server = HTTPServer(("127.0.0.1", 0), AnthropicHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        backend = AnthropicCompatibleBackend(
            f"http://127.0.0.1:{server.server_port}", "secret"
        )
        result = backend.generate(
            system_prompt="test",
            payload={"pending_inbox_events": []},
            model="compatible-small",
        )
        assert result["changed"] is False
    finally:
        server.shutdown()
        thread.join()
