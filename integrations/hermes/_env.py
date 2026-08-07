"""Shared config loading for the OpenEgiz MCP servers.

Secrets never live in ~/.hermes/config.yaml. Instead each MCP server reads a
plain KEY=VALUE file (default ~/.config/openegiz-mcp.env, chmod 600) at
startup and merges it into os.environ. Real environment variables always win,
so a value can still be overridden per-server from the Hermes config.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ENV_FILE = "~/.config/openegiz-mcp.env"


def load_env_file(path: str | None = None) -> None:
    """Merge KEY=VALUE lines from the OpenEgiz env file into os.environ.

    Missing file is not an error: the servers have working defaults for
    everything except the InfluxDB token.
    """
    raw = path or os.environ.get("OPENEGIZ_ENV_FILE") or DEFAULT_ENV_FILE
    f = Path(raw).expanduser()
    if not f.is_file():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Do not clobber a value that was explicitly exported for this process.
        os.environ.setdefault(key, value)
