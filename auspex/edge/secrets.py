"""The agent host's secrets file (D-063): a JSON object of name → value, mode 0600.
Auspex never holds these; an integration's config names them (`secret:<name>`). Read
again for every job, so a rotated secret needs no restart."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path


class SecretsFileRefused(ValueError):
    """The file is missing, readable by others, or not a JSON object of strings."""


def load(path: Path) -> dict[str, str]:
    try:
        mode = os.stat(path).st_mode
    except OSError as err:
        raise SecretsFileRefused(f"secrets file {path}: {err.strerror}") from err
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise SecretsFileRefused(
            f"secrets file {path} is readable by others; chmod it to 0600")
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise SecretsFileRefused(f"secrets file {path} is not valid JSON") from err
    if not isinstance(data, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise SecretsFileRefused(f"secrets file {path} must map names to string values")
    return data
