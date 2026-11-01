"""配置持久化：记住面板地址、上次粘贴的启动命令、窗口大小等。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from frp_client import paths


def default_config() -> dict[str, Any]:
    return {
        "panel_url": paths.DEFAULT_PANEL_URL,
        "command": "",
        "mc_confirmed": False,
        "guide_done": False,
        "close_action": "tray",
        "appearance": {},
        "window_size": [1300, 850],
        "window_pos": None,
    }


def load(path: Path | None = None) -> dict[str, Any]:
    """读取配置文件，失败时返回默认配置。"""
    path = path or paths.CONFIG_FILE
    config = default_config()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return config

    if isinstance(raw, dict):
        for key in config:
            if key in raw:
                config[key] = raw[key]
    return config


def save(config: dict[str, Any], path: Path | None = None) -> None:
    """写入配置文件，失败时静默忽略（不影响主流程）。"""
    path = path or paths.CONFIG_FILE
    try:
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
