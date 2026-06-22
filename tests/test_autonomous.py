from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from innerlife.autonomous import AutonomousExperienceEngine
from innerlife.config import Settings
from innerlife.llm import FakeBackend


ARTICLE = """
<html><head><title>A life beyond direct conversation</title></head>
<body><article>
<h1>A life beyond direct conversation</h1>
<p>An enduring mind needs encounters that are not supplied by one conversation partner.</p>
<p>Reading public work can create grounded experience when the source, time, and evidence remain visible.</p>
<p>The important distinction is between encountering material and pretending that an event happened.</p>
</article></body></html>
"""


class SourceHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/feed.xml":
            body = f"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Test source</title>
<item><title>A life beyond direct conversation</title>
<link>http://127.0.0.1:{self.server.server_port}/article</link>
<description>A grounded autonomous encounter.</description>
</item></channel></rss>""".encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml")
        elif self.path == "/article":
            body = ARTICLE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        else:
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def start_source_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), SourceHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def settings_for(tmp_path, monkeypatch) -> Settings:
    monkeypatch.setenv("INNERLIFE_ROOT", str(tmp_path))
    monkeypatch.setenv("INNERLIFE_DB_PATH", str(tmp_path / "innerlife.db"))
    monkeypatch.setenv("INNERLIFE_LLM_BACKEND", "fake")
    return Settings.from_env()


def successful_responder(payload):
    if "candidates" in payload:
        return {
            "selected": True,
            "candidate_id": payload["candidates"][0]["candidate_id"],
            "reason": "它直接关系到主体如何获得不依赖用户的真实输入",
        }
    if "evidence" in payload:
        return {
            "worth_digesting": True,
            "experience_summary": "我读到，自主经历必须保留真实来源，而不是虚构生活。",
            "why_it_mattered": "这改变了我对自主性的判断标准。",
            "new_questions": ["选择来源本身会不会逐渐形成偏好？"],
            "possible_revision": "今后优先保留可核查证据。",
        }
    event = payload["pending_inbox_events"][-1]
    return {
        "changed": True,
        "reason": "这次阅读形成了一个新的判断标准",
        "internal_events": [
            {
                "event_type": "new_insight",
                "content": "自主经历必须有可核查来源，不能靠虚构填充。",
                "source_refs": [event["id"]],
            }
        ],
        "state_update": {
            "recent_focus": "有证据的自主经历",
            "open_loops": [
                {
                    "content": "选择来源是否会逐渐形成稳定偏好",
                    "source_refs": [event["id"]],
                }
            ],
        },
        "pending_shares": [],
    }


def test_autonomous_experience_fetches_real_material_and_enters_digest(
    storage, tmp_path, monkeypatch
):
    server = start_source_server()
    try:
        storage.add_source(
            "agent-a",
            "Local grounded source",
            f"http://127.0.0.1:{server.server_port}/feed.xml",
        )
        for source in storage.list_sources("agent-a"):
            if source["name"] != "Local grounded source":
                with storage.transaction() as conn:
                    conn.execute(
                        "UPDATE source_subscriptions SET enabled=0 WHERE id=?",
                        (source["id"],),
                    )
        engine = AutonomousExperienceEngine(
            storage,
            settings_for(tmp_path, monkeypatch),
            FakeBackend(responder=successful_responder),
        )
        result = engine.explore("agent-a")
    finally:
        server.shutdown()
        server.server_close()

    assert result["experience"]["url"].endswith("/article")
    assert result["experience"]["evidence"]["text_chars"] >= 200
    assert result["digest"]["changed"] is True
    assert storage.pending_events("agent-a") == []
    assert len(storage.list_autonomous_experiences("agent-a")) == 1
    assert storage.list_exploration_runs("agent-a")[0]["status"] == "experienced"
    assert storage.get_agent("agent-a")["state"]["recent_focus"] == "有证据的自主经历"


def test_autonomous_experience_can_choose_to_skip(storage, tmp_path, monkeypatch):
    server = start_source_server()
    try:
        storage.add_source(
            "agent-b",
            "Local grounded source",
            f"http://127.0.0.1:{server.server_port}/feed.xml",
        )
        for source in storage.list_sources("agent-b"):
            if source["name"] != "Local grounded source":
                with storage.transaction() as conn:
                    conn.execute(
                        "UPDATE source_subscriptions SET enabled=0 WHERE id=?",
                        (source["id"],),
                    )
        backend = FakeBackend(
            responder=lambda payload: {
                "selected": False,
                "candidate_id": None,
                "reason": "今天没有真正值得进入内在状态的材料",
            }
        )
        result = AutonomousExperienceEngine(
            storage, settings_for(tmp_path, monkeypatch), backend
        ).explore("agent-b")
    finally:
        server.shutdown()
        server.server_close()

    assert result["selected"] is False
    assert storage.list_autonomous_experiences("agent-b") == []
    assert storage.list_exploration_runs("agent-b")[0]["status"] == "skipped"


def test_duplicate_material_does_not_create_second_experience(
    storage, tmp_path, monkeypatch
):
    server = start_source_server()
    try:
        storage.add_source(
            "agent-a",
            "Local grounded source",
            f"http://127.0.0.1:{server.server_port}/feed.xml",
        )
        for source in storage.list_sources("agent-a"):
            if source["name"] != "Local grounded source":
                with storage.transaction() as conn:
                    conn.execute(
                        "UPDATE source_subscriptions SET enabled=0 WHERE id=?",
                        (source["id"],),
                    )
        engine = AutonomousExperienceEngine(
            storage,
            settings_for(tmp_path, monkeypatch),
            FakeBackend(responder=successful_responder),
        )
        engine.explore("agent-a")
        result = engine.explore("agent-a")
    finally:
        server.shutdown()
        server.server_close()

    assert result["selected"] is False
    assert "已经" in result["reason"]
    assert len(storage.list_autonomous_experiences("agent-a")) == 1
    assert storage.list_exploration_runs("agent-a")[0]["status"] == "duplicate"


def test_sources_and_experiences_remain_agent_isolated(storage):
    storage.add_source(
        "agent-a",
        "Agent A only",
        "https://example.com/agent-a.xml",
    )
    agent_a_urls = {source["url"] for source in storage.list_sources("agent-a")}
    agent_b_urls = {source["url"] for source in storage.list_sources("agent-b")}

    assert "https://example.com/agent-a.xml" in agent_a_urls
    assert "https://example.com/agent-a.xml" not in agent_b_urls
