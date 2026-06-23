from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Any

from .config import PROJECT_ROOT, Settings
from .digest import DigestEngine, make_backend
from .models import ModelError, ValidationError, active_state_view
from .storage import Storage, new_id, utc_now


USER_AGENT = "InnerLife/2.3 (+autonomous-experience; read-only)"


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            value = re.sub(r"\s+", " ", data).strip()
            if value:
                self.parts.append(value)

    def text(self) -> str:
        return "\n".join(self.parts)


def _fetch(url: str, timeout: float = 20, max_bytes: int = 2_000_000) -> tuple[bytes, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationError(f"Only public HTTP sources are supported: {url}")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, text/html, application/xml;q=0.9, */*;q=0.1",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get_content_type()
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValidationError(f"Source response too large: {url}")
    return data, content_type


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, names: set[str]) -> str:
    for child in list(element):
        if _local_name(child.tag) in names:
            return "".join(child.itertext()).strip()
    return ""


def fetch_candidates(source: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    data, content_type = _fetch(source["url"])
    if source.get("source_type") == "webpage" or content_type == "text/html":
        parser = TextExtractor()
        parser.feed(data.decode("utf-8", errors="replace"))
        text = parser.text()
        title_match = re.search(r"<title[^>]*>(.*?)</title>", data.decode("utf-8", errors="replace"), re.I | re.S)
        title = html.unescape(re.sub(r"\s+", " ", title_match.group(1)).strip()) if title_match else source["name"]
        return [
            {
                "candidate_id": hashlib.sha256(source["url"].encode()).hexdigest()[:16],
                "source_name": source["name"],
                "title": title,
                "url": source["url"],
                "published_at": None,
                "summary": text[:1200],
            }
        ]
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValidationError(f"Invalid RSS/Atom source {source['url']}: {exc}") from exc
    items = [
        element
        for element in root.iter()
        if _local_name(element.tag) in {"item", "entry"}
    ]
    candidates: list[dict[str, Any]] = []
    for item in items[:limit]:
        title = _child_text(item, {"title"})
        summary = _child_text(item, {"summary", "description", "content"})
        published = _child_text(item, {"published", "updated", "pubDate", "date"})
        url = _child_text(item, {"link"})
        if not url:
            for child in list(item):
                if _local_name(child.tag) == "link" and child.attrib.get("href"):
                    url = child.attrib["href"]
                    break
        if not title or not url:
            continue
        url = urllib.parse.urljoin(source["url"], url)
        candidates.append(
            {
                "candidate_id": hashlib.sha256(url.encode()).hexdigest()[:16],
                "source_name": source["name"],
                "title": html.unescape(title),
                "url": url,
                "published_at": published or None,
                "summary": re.sub(r"<[^>]+>", " ", html.unescape(summary))[:1600],
            }
        )
    return candidates


def read_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    data, content_type = _fetch(candidate["url"])
    decoded = data.decode("utf-8", errors="replace")
    if content_type in {"text/html", "application/xhtml+xml"} or "<html" in decoded[:500].lower():
        parser = TextExtractor()
        parser.feed(decoded)
        text = parser.text()
    else:
        text = decoded
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 200:
        raise ValidationError("Fetched material did not contain enough readable text")
    bounded = text[:30_000]
    return {
        "source_name": candidate["source_name"],
        "title": candidate["title"],
        "url": candidate["url"],
        "published_at": candidate.get("published_at"),
        "fetched_at": utc_now(),
        "text": bounded,
        "text_chars": len(bounded),
        "content_fingerprint": hashlib.sha256(bounded.encode("utf-8")).hexdigest(),
    }


def _prompt(name: str) -> str:
    return (PROJECT_ROOT / "prompts" / name).read_text(encoding="utf-8")


def _retry_json(backend, prompt: str, payload: dict[str, Any], model: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(2):
        current = prompt
        if attempt:
            current += "\n\n上一次输出无法读取。不要解释，只返回指定 JSON。"
        try:
            value = backend.generate(system_prompt=current, payload=payload, model=model)
            if not isinstance(value, dict):
                raise ModelError("Expected JSON object")
            return value
        except Exception as exc:
            last_error = exc
    raise ValidationError(f"Model output failed after retry: {last_error}")


class AutonomousExperienceEngine:
    def __init__(self, storage: Storage, settings: Settings, backend=None):
        self.storage = storage
        self.settings = settings
        self.backend = backend or make_backend(settings)

    def explore(self, agent_id: str, process_now: bool = True) -> dict[str, Any]:
        run_id = new_id("explore")
        sources = self.storage.list_sources(agent_id)
        agent = self.storage.get_agent(agent_id)
        candidates: list[dict[str, Any]] = []
        source_errors: list[dict[str, str]] = []
        for source in sources:
            try:
                candidates.extend(fetch_candidates(source))
            except Exception as exc:
                source_errors.append({"source": source["name"], "error": str(exc)})
        deduped = {item["candidate_id"]: item for item in candidates}
        candidates = list(deduped.values())[:50]
        if not candidates:
            result = {"selected": False, "reason": "没有可读取的候选材料", "source_errors": source_errors}
            self.storage.record_exploration_run(
                run_id=run_id,
                agent_id=agent_id,
                status="no_candidates",
                candidate_count=0,
                result=result,
                error=json.dumps(source_errors, ensure_ascii=False) if source_errors else None,
            )
            return {"run_id": run_id, **result}

        selection_raw = _retry_json(
            self.backend,
            _prompt("exploration_select.md"),
            {
                "agent_id": agent_id,
                "profile": agent["profile"],
                "state": active_state_view(agent["state"]),
                "recent_experiences": self.storage.list_autonomous_experiences(agent_id, 10),
                "stable_summaries": self.storage.list_inner_summaries(agent_id, 10),
                "candidates": candidates,
            },
            self.settings.model_for("light"),
        )
        selected = bool(selection_raw.get("selected"))
        reason = str(selection_raw.get("reason") or "").strip()
        if not reason:
            raise ValidationError("Exploration selection requires reason")
        if not selected:
            result = {"selected": False, "reason": reason, "source_errors": source_errors}
            self.storage.record_exploration_run(
                run_id=run_id,
                agent_id=agent_id,
                status="skipped",
                candidate_count=len(candidates),
                result=result,
                selection_reason=reason,
            )
            return {"run_id": run_id, **result}
        candidate_id = str(selection_raw.get("candidate_id") or "")
        candidate = next(
            (item for item in candidates if item["candidate_id"] == candidate_id),
            None,
        )
        if candidate is None:
            raise ValidationError("Model selected an unavailable candidate")

        try:
            evidence = read_candidate(candidate)
        except Exception as exc:
            result = {"selected": True, "candidate": candidate, "error": str(exc)}
            self.storage.record_exploration_run(
                run_id=run_id,
                agent_id=agent_id,
                status="fetch_failed",
                candidate_count=len(candidates),
                result=result,
                selected_url=candidate["url"],
                selection_reason=reason,
                error=str(exc),
            )
            return {"run_id": run_id, **result}
        if evidence["content_fingerprint"] in self.storage.known_experience_fingerprints(agent_id):
            result = {"selected": False, "reason": "这份材料已经形成过自主经历", "candidate": candidate}
            self.storage.record_exploration_run(
                run_id=run_id,
                agent_id=agent_id,
                status="duplicate",
                candidate_count=len(candidates),
                result=result,
                selected_url=candidate["url"],
                selection_reason=reason,
            )
            return {"run_id": run_id, **result}

        reflection = _retry_json(
            self.backend,
            _prompt("exploration_reflect.md"),
            {
                "agent_id": agent_id,
                "profile": agent["profile"],
                "state": active_state_view(agent["state"]),
                "selection_reason": reason,
                "evidence": evidence,
            },
            self.settings.model_for("light"),
        )
        evidence_record = {
            "source_name": evidence["source_name"],
            "title": evidence["title"],
            "url": evidence["url"],
            "published_at": evidence["published_at"],
            "fetched_at": evidence["fetched_at"],
            "text_chars": evidence["text_chars"],
            "content_fingerprint": evidence["content_fingerprint"],
            "text_excerpt": evidence["text"][:4000],
        }
        worth_raw = reflection.get("worth_digesting")
        if not isinstance(worth_raw, bool):
            raise ValidationError("Autonomous experience reflection requires boolean worth_digesting")
        worth = worth_raw
        result = {
            "selected": True,
            "candidate": candidate,
            "selection_reason": reason,
            "evidence": evidence_record,
            "reflection": reflection,
        }
        if not worth:
            self.storage.record_exploration_run(
                run_id=run_id,
                agent_id=agent_id,
                status="read_no_change",
                candidate_count=len(candidates),
                result=result,
                selected_url=candidate["url"],
                selection_reason=reason,
            )
            return {"run_id": run_id, **result, "experience": None, "digest": None}

        summary = str(reflection.get("experience_summary") or "").strip()
        why = str(reflection.get("why_it_mattered") or "").strip()
        questions = reflection.get("new_questions") or []
        revision = str(reflection.get("possible_revision") or "").strip()
        if (
            not summary
            or not why
            or not isinstance(questions, list)
            or any(not isinstance(question, str) for question in questions)
        ):
            raise ValidationError("Autonomous experience reflection is incomplete")
        experience_id = new_id("experience")
        self.storage.record_exploration_run(
            run_id=run_id,
            agent_id=agent_id,
            status="processing",
            candidate_count=len(candidates),
            result=result,
            selected_url=candidate["url"],
            selection_reason=reason,
        )
        experience = self.storage.save_autonomous_experience(
            experience_id=experience_id,
            agent_id=agent_id,
            run_id=run_id,
            source_name=evidence["source_name"],
            title=evidence["title"],
            url=evidence["url"],
            published_at=evidence["published_at"],
            fetched_at=evidence["fetched_at"],
            content_fingerprint=evidence["content_fingerprint"],
            evidence=evidence_record,
            experience={
                "experience_summary": summary,
                "why_it_mattered": why,
                "new_questions": questions,
                "possible_revision": revision,
                "selection_reason": reason,
            },
        )
        event = self.storage.submit_event(
            agent_id,
            "autonomous_experience",
            experience_id,
            {
                "experience_id": experience_id,
                "title": evidence["title"],
                "url": evidence["url"],
                "text": summary,
                "why_it_mattered": why,
                "new_questions": questions,
                "possible_revision": revision,
                "user_involved": False,
            },
            event_id=f"autonomous_{experience_id}",
        )
        digest = None
        if process_now:
            try:
                digest = DigestEngine(self.storage, self.backend).run(
                    agent_id, "light", self.settings.model_for("light")
                ).to_dict()
            except Exception as exc:
                self.storage.record_exploration_run(
                    run_id=run_id,
                    agent_id=agent_id,
                    status="experience_pending_digest",
                    candidate_count=len(candidates),
                    result={
                        **result,
                        "experience_id": experience_id,
                        "event_id": event["id"],
                    },
                    selected_url=candidate["url"],
                    selection_reason=reason,
                    error=str(exc),
                )
                raise
        self.storage.record_exploration_run(
            run_id=run_id,
            agent_id=agent_id,
            status="experienced",
            candidate_count=len(candidates),
            result={**result, "experience_id": experience_id, "event_id": event["id"]},
            selected_url=candidate["url"],
            selection_reason=reason,
        )
        return {
            "run_id": run_id,
            **result,
            "experience": experience,
            "event": event,
            "digest": digest,
        }
