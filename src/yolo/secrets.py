"""Resolve @secrets:<key> references from ~/.config/yolo/secrets.yaml."""

import os
import stat
from pathlib import Path

from ruamel.yaml import YAML


SECRETS_FILENAME = "secrets.yaml"
SECRETS_PREFIX = "@secrets:"
REQUIRED_MODE = 0o600

_yaml = YAML(typ="safe")


class SecretsError(Exception):
    """Raised when secrets.yaml can't be loaded or a reference can't be resolved."""


def _secrets_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "yolo" / SECRETS_FILENAME


def load_secrets(path: Path | None = None) -> dict[str, str]:
    """Load secrets.yaml, enforcing mode 0600.

    Returns {} if the file doesn't exist. Callers that hit an unresolved
    @secrets: reference will raise regardless, so missing-file is fine here.
    """
    if path is None:
        path = _secrets_path()
    if not path.is_file():
        return {}

    st = path.stat()
    mode = stat.S_IMODE(st.st_mode)
    if mode != REQUIRED_MODE:
        raise SecretsError(
            f"{path} has mode {mode:04o}, expected 0600.\nFix with: chmod 600 {path}"
        )

    data = _yaml.load(path)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SecretsError(f"{path} must be a flat YAML map of key: value")
    return {str(k): str(v) for k, v in data.items()}


def resolve_env_entry(
    entry: str,
    secrets: dict[str, str],
    secrets_path: Path | None = None,
) -> str:
    """Resolve a single env entry, expanding @secrets:<key> on the value side.

    Bare names and literal KEY=VALUE entries pass through unchanged.
    Raises SecretsError if a reference is unresolvable.
    """
    if "=" not in entry:
        return entry
    key, _, value = entry.partition("=")
    if not value.startswith(SECRETS_PREFIX):
        return entry

    ref = value[len(SECRETS_PREFIX) :]
    if not ref:
        raise SecretsError(f"Empty secret key in {key}={value!r}")

    if not secrets:
        path = secrets_path or _secrets_path()
        raise SecretsError(
            f"{key}={value!r} references secrets.yaml but {path} does not exist"
        )

    if ref not in secrets:
        raise SecretsError(f"Secret {ref!r} not found in secrets.yaml (used by {key})")

    resolved = secrets[ref]
    if resolved == "":
        raise SecretsError(f"Secret {ref!r} is empty (used by {key})")

    return f"{key}={resolved}"


def resolve_env(entries: list[str]) -> list[str]:
    """Resolve @secrets: references across an env list.

    Loads secrets.yaml lazily — only if at least one entry uses @secrets:.
    """
    needs_secrets = any(
        "=" in e and e.split("=", 1)[1].startswith(SECRETS_PREFIX) for e in entries
    )
    secrets = load_secrets() if needs_secrets else {}
    return [resolve_env_entry(e, secrets) for e in entries]
