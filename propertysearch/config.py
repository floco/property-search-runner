"""Runner configuration from config/settings.env (KEY=value lines; environment overrides)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "config" / "settings.env"


class ConfigError(Exception):
    pass


@dataclass
class Config:
    myhome_url: str
    myhome_token: str
    claude_bin: str = "/root/.local/bin/claude"
    timeout_s: int = 1500


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_config(path: Path = SETTINGS) -> Config:
    values = {**_read_env_file(path), **{k: v for k, v in os.environ.items() if k.startswith(("MYHOME_", "CLAUDE_BIN", "TIMEOUT_S"))}}
    url, token = values.get("MYHOME_URL", ""), values.get("MYHOME_TOKEN", "")
    if not url or not token:
        raise ConfigError(f"MYHOME_URL and MYHOME_TOKEN must be set in {path}")
    return Config(myhome_url=url, myhome_token=token,
                  claude_bin=values.get("CLAUDE_BIN") or Config.claude_bin,
                  timeout_s=int(values.get("TIMEOUT_S") or Config.timeout_s))
