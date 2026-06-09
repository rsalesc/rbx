"""Cheap, tolerant reads of package YAML for completion. No pydantic, no full load."""

import functools
from pathlib import Path
from typing import Any, Dict

import yaml


def _read_yaml(path: Path) -> Dict[str, Any]:
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


@functools.lru_cache(maxsize=64)
def _peek_cached(path_str: str, mtime: float) -> Dict[str, Any]:
    return _read_yaml(Path(path_str))


def peek(path: Path) -> Dict[str, Any]:
    """mtime-keyed cache so repeated tabs are instant."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    return _peek_cached(str(path), mtime)
