from __future__ import annotations

import json
import time
import urllib.request
from typing import Any


class FeishuDelivery:
    """Send messages via Feishu API."""

    BASE = "https://open.feishu.cn/open-apis"

    def __init__(self, app_id: str, app_secret: str, receive_id: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.receive_id = receive_id
        self._token: str | None = None
        self._token_expiry: float = 0.0

    def _get_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expiry - 300:
            return self._token
        url = f"{self.BASE}/auth/v3/tenant_access_token/internal"
        body = json.dumps(
            {"app_id": self.app_id, "app_secret": self.app_secret}
        ).encode()
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        code = data.get("code", -1)
        if code != 0:
            raise RuntimeError(f"Feishu token failed: {data.get('msg', data)}")
        self._token = data["tenant_access_token"]
        self._token_expiry = now + data.get("expire", 7200)
        return self._token  # type: ignore[return-value]

    def send(self, text: str) -> dict[str, Any]:
        token = self._get_token()
        url = (
            f"{self.BASE}/im/v1/messages"
            f"?receive_id_type=chat_id"
        )
        content = json.dumps({"text": text}, ensure_ascii=False)
        body = json.dumps(
            {
                "receive_id": self.receive_id,
                "msg_type": "text",
                "content": content,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
        code = result.get("code", -1)
        if code != 0:
            raise RuntimeError(f"Feishu send failed: {result.get('msg', result)}")
        return result
