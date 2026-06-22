from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEGACY_ROOT = Path.home() / ".claracore" / "innerlife"
DEFAULT_ROOT = LEGACY_ROOT if LEGACY_ROOT.exists() else Path.home() / ".innerlife"


def _load_env_file(root: Path) -> None:
    _load_named_env_file(root / "innerlife.env")


def _load_named_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    root: Path
    db_path: Path
    backend: str
    base_url: str
    api_key: str
    light_model: str
    deep_model: str
    timeout_seconds: float
    poll_seconds: float
    light_idle_seconds: float
    deep_idle_seconds: float
    memoria_db_path: Path
    continuity_db_path: Path
    memoria_sync_agents: tuple[str, ...]
    continuity_sync_agents: tuple[str, ...]
    autonomy_enabled: bool

    @classmethod
    def from_env(cls) -> "Settings":
        root = Path(os.environ.get("INNERLIFE_ROOT", str(DEFAULT_ROOT))).expanduser()
        _load_env_file(root)
        configured_root = Path(
            os.environ.get("INNERLIFE_ROOT", str(root))
        ).expanduser()
        if configured_root != root:
            root = configured_root
            _load_env_file(root)
        else:
            root = configured_root
        secret_file_value = os.environ.get("INNERLIFE_SECRET_ENV_FILE", "").strip()
        if secret_file_value:
            _load_named_env_file(Path(secret_file_value).expanduser())
        return cls(
            root=root,
            db_path=Path(
                os.environ.get(
                    "INNERLIFE_DB_PATH",
                    str(root / "innerlife.db"),
                )
            ).expanduser(),
            backend=os.environ.get("INNERLIFE_LLM_BACKEND", "fake"),
            base_url=os.environ.get("INNERLIFE_LLM_BASE_URL", "http://127.0.0.1:11434/v1"),
            api_key=os.environ.get("INNERLIFE_LLM_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY", ""),
            light_model=os.environ.get("INNERLIFE_LIGHT_MODEL", "gemma3:4b"),
            deep_model=os.environ.get("INNERLIFE_DEEP_MODEL", "gemma3:12b"),
            timeout_seconds=float(os.environ.get("INNERLIFE_LLM_TIMEOUT", "120")),
            poll_seconds=float(os.environ.get("INNERLIFE_POLL_SECONDS", "15")),
            light_idle_seconds=float(
                os.environ.get("INNERLIFE_LIGHT_IDLE_SECONDS", "7200")
            ),
            deep_idle_seconds=float(
                os.environ.get("INNERLIFE_DEEP_IDLE_SECONDS", "72000")
            ),
            memoria_db_path=Path(
                os.environ.get(
                    "INNERLIFE_MEMORIA_DB",
                    str(Path.home() / ".memoria" / "memoria.db"),
                )
            ).expanduser(),
            continuity_db_path=Path(
                os.environ.get(
                    "INNERLIFE_CONTINUITY_DB",
                    str(Path.home() / ".continuity" / "continuity.db"),
                )
            ).expanduser(),
            memoria_sync_agents=tuple(
                item.strip()
                for item in os.environ.get(
                    "INNERLIFE_MEMORIA_SYNC_AGENTS", ""
                ).split(",")
                if item.strip()
            ),
            continuity_sync_agents=tuple(
                item.strip()
                for item in os.environ.get(
                    "INNERLIFE_CONTINUITY_SYNC_AGENTS", ""
                ).split(",")
                if item.strip()
            ),
            autonomy_enabled=os.environ.get(
                "INNERLIFE_AUTONOMY_ENABLED", "true"
            ).lower()
            in {"1", "true", "yes", "on"},
        )

    def model_for(self, mode: str) -> str:
        return self.deep_model if mode == "deep" else self.light_model
