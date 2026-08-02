"""Config loading/saving for the Gemini Enterprise Agent Platform Memory Bank plugin.

Precedence: environment variables provide defaults; $HERMES_HOME/vertex_memory.json
overrides individual keys. No secrets are stored — auth is via ADC.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_ENV_MAP = {
    "project_id": "VERTEX_MEMORY_PROJECT_ID",
    "location": "VERTEX_MEMORY_LOCATION",
    "reasoning_engine_id": "VERTEX_MEMORY_ENGINE_ID",
    "scope_key": "VERTEX_MEMORY_SCOPE_KEY",
    "scope_value": "VERTEX_MEMORY_SCOPE_VALUE",
    "top_k": "VERTEX_MEMORY_TOP_K",
    "max_distance": "VERTEX_MEMORY_MAX_DISTANCE",
}

_DEFAULTS = {
    "location": "us-central1",
    "scope_key": "user_id",
    "top_k": "10",
}

_CONFIG_FILENAME = "vertex_memory.json"


def _hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home
        return get_hermes_home()
    except Exception:
        return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


def load_config() -> dict:
    """Merge defaults < env vars < $HERMES_HOME/vertex_memory.json."""
    cfg = dict(_DEFAULTS)
    for key, env in _ENV_MAP.items():
        val = os.environ.get(env)
        if val:
            cfg[key] = val

    cfg_path = _hermes_home() / _CONFIG_FILENAME
    if cfg_path.exists():
        try:
            file_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            cfg.update({k: v for k, v in file_cfg.items()
                        if v is not None and v != ""})
        except Exception:
            pass
    return cfg


def save_config_file(values: dict, hermes_home: str) -> None:
    """Persist non-secret config to $HERMES_HOME/vertex_memory.json."""
    cfg_path = Path(hermes_home) / _CONFIG_FILENAME
    existing = {}
    if cfg_path.exists():
        try:
            existing = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    existing.update({k: v for k, v in values.items() if v not in (None, "")})
    cfg_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
