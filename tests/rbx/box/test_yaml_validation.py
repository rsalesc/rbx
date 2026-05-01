"""Unit tests for rbx.box.yaml_validation."""

from __future__ import annotations

import ruyaml


def _parse(text: str) -> ruyaml.comments.CommentedBase:
    """Parse YAML text with ruyaml in round-trip mode for tests."""
    return ruyaml.YAML(typ='rt').load(text)
