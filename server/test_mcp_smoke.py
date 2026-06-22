#!/usr/bin/env python
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server" / "mcp.py"


class Client:
    def __init__(self, env):
        self.process = subprocess.Popen(
            [sys.executable, str(SERVER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self.request_id = 0

    def request(self, method, params=None):
        self.request_id += 1
        message = {"jsonrpc": "2.0", "id": self.request_id, "method": method}
        if params is not None:
            message["params"] = params
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline())

    def notify(self, method):
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.process.stdin.flush()

    def close(self):
        self.process.terminate()
        self.process.wait(timeout=5)


def content(response):
    return json.loads(response["result"]["content"][0]["text"])


def main():
    with tempfile.TemporaryDirectory(prefix="innerlife-mcp-") as tmp:
        env = os.environ.copy()
        env["INNERLIFE_DB_PATH"] = str(Path(tmp) / "innerlife.db")
        env["INNERLIFE_AGENT_ID"] = "example-agent"
        subprocess.run(
            [sys.executable, "-m", "innerlife.cli", "init", "--json"],
            env=env,
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        client = Client(env)
        initialized = client.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "1"},
            },
        )
        assert initialized["result"]["serverInfo"]["name"] == "innerlife"
        client.notify("notifications/initialized")
        tools = client.request("tools/list")["result"]["tools"]
        assert len(tools) == 14
        started = content(
            client.request(
                "tools/call",
                {
                    "name": "innerlife_session_start",
                    "arguments": {
                        "user_id": "example-user",
                        "host": "mcp-smoke",
                        "external_session_id": "mcp-session-1",
                    },
                },
            )
        )
        assert started["session"]["status"] == "active"
        submitted = content(
            client.request(
                "tools/call",
                {
                    "name": "innerlife_record_afterthought",
                    "arguments": {
                        "source_session": "mcp-smoke",
                        "agent_afterthought": "需要验证 MCP 可以接入真实对话",
                    },
                },
            )
        )
        assert submitted["status"] == "pending"
        briefing = content(
            client.request(
                "tools/call",
                {"name": "innerlife_briefing", "arguments": {}},
            )
        )
        assert briefing["agent_id"] == "example-agent"
        status = content(
            client.request("tools/call", {"name": "innerlife_status", "arguments": {}})
        )
        assert status["stats"]["pending_inbox"] == 1
        client.close()
    print("InnerLife MCP smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
