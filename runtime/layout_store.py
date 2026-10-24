"""Small, DSH-owned persistence layer for companion window layout."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_LAYOUT: dict[str, Any] = {
    "version": 1,
    "x": None,
    "y": None,
    "petX": None,
    "petY": None,
    "scale": 1.0,
    "bubbleScale": 1.0,
    "reducedMotion": False,
}


def default_layout_path() -> Path:
    override = os.environ.get("DSH_DAFEIYU_LAYOUT_PATH")
    if override:
        return Path(override)
    dsh_home = os.environ.get("DSH_HOME")
    if dsh_home:
        return Path(dsh_home) / "dsh-dafeiyu" / "layout.json"
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "DSH" / "dsh-dafeiyu" / "layout.json"
    return Path.home() / ".dsh" / "dsh-dafeiyu" / "layout.json"


def normalise_layout(value: Any) -> dict[str, Any]:
    layout = dict(DEFAULT_LAYOUT)
    if not isinstance(value, dict):
        return layout
    for key in ("x", "y", "petX", "petY"):
        coordinate = value.get(key)
        if isinstance(coordinate, int) and not isinstance(coordinate, bool):
            layout[key] = coordinate
    scale = value.get("scale")
    if isinstance(scale, (int, float)) and not isinstance(scale, bool):
        layout["scale"] = min(1.4, max(0.7, float(scale)))
    bubble_scale = value.get("bubbleScale")
    if isinstance(bubble_scale, (int, float)) and not isinstance(bubble_scale, bool):
        layout["bubbleScale"] = min(1.2, max(0.8, float(bubble_scale)))
    if isinstance(value.get("reducedMotion"), bool):
        layout["reducedMotion"] = value["reducedMotion"]
    return layout


def load_layout(path: Path) -> dict[str, Any]:
    try:
        return normalise_layout(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return dict(DEFAULT_LAYOUT)


def save_layout(path: Path, value: dict[str, Any]) -> None:
    layout = normalise_layout(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A fixed per-process temp name avoids `tempfile.mkstemp`, whose random-name
    # sequence deadlocked inside the PyInstaller one-file helper on Windows.
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(layout, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
