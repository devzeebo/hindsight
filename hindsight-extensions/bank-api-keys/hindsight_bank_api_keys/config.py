"""YAML config loading, validation, and hot-reload cache."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from hindsight_bank_api_keys.crypto import verify_secret

ADMIN_KEY_ID = "admin"
DEFAULT_RELOAD_INTERVAL_SECONDS = 30


@dataclass(frozen=True)
class AdminKeySpec:
    """Resolved admin key material (full access)."""

    secret: str


@dataclass(frozen=True)
class ApiKeySpec:
    """One configured API key after secret resolution."""

    id: str
    name: str
    secret: str
    all_banks: bool
    banks: tuple[str, ...] = ()


@dataclass
class BankApiKeysConfig:
    """Parsed, validated configuration ready for auth lookups."""

    admin: AdminKeySpec | None
    keys: tuple[ApiKeySpec, ...]
    keys_by_id: dict[str, ApiKeySpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        by_id: dict[str, ApiKeySpec] = {key.id: key for key in self.keys}
        object.__setattr__(self, "keys_by_id", by_id)


@dataclass(frozen=True)
class AuthMatch:
    """Result of matching a bearer token to a configured key."""

    key_id: str
    all_banks: bool
    banks: tuple[str, ...]


class ConfigError(ValueError):
    """Raised when the YAML config is invalid."""


def _require_mapping(raw: Any, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigError(f"{label} must be a mapping")
    return raw


def _resolve_secret_fields(entry: dict[str, Any], label: str) -> str:
    has_secret = "secret" in entry and entry["secret"] is not None
    has_secret_env = "secret_env" in entry and entry["secret_env"] is not None
    has_secret_hash = "secret_hash" in entry and entry["secret_hash"] is not None

    provided = sum(1 for flag in (has_secret, has_secret_env, has_secret_hash) if flag)
    if provided != 1:
        raise ConfigError(f"{label} must specify exactly one of secret, secret_env, or secret_hash")

    if has_secret:
        secret = entry["secret"]
        if not isinstance(secret, str) or not secret:
            raise ConfigError(f"{label}.secret must be a non-empty string")
        return secret

    if has_secret_env:
        env_name = entry["secret_env"]
        if not isinstance(env_name, str) or not env_name:
            raise ConfigError(f"{label}.secret_env must be a non-empty string")
        value = os.environ.get(env_name)
        if value is None or value == "":
            raise ConfigError(f"{label}.secret_env references unset or empty environment variable {env_name!r}")
        return value

    secret_hash = entry["secret_hash"]
    if not isinstance(secret_hash, str) or not secret_hash:
        raise ConfigError(f"{label}.secret_hash must be a non-empty string")
    # Hashed keys cannot be matched at load time; store the hash marker for verify at auth.
    return f"hash:{secret_hash}"


def _parse_admin(raw: Any) -> AdminKeySpec | None:
    if raw is None:
        return None
    entry = _require_mapping(raw, "admin")
    secret = _resolve_secret_fields(entry, "admin")
    if secret.startswith("hash:"):
        raise ConfigError("admin must use secret or secret_env, not secret_hash")
    return AdminKeySpec(secret=secret)


def _parse_key(entry: Any, index: int) -> ApiKeySpec:
    block = _require_mapping(entry, f"keys[{index}]")
    key_id = block.get("id")
    name = block.get("name")
    if not isinstance(key_id, str) or not key_id:
        raise ConfigError(f"keys[{index}].id must be a non-empty string")
    if not isinstance(name, str) or not name:
        raise ConfigError(f"keys[{index}].name must be a non-empty string")

    all_banks = bool(block.get("all_banks", False))
    banks_raw = block.get("banks")
    banks: tuple[str, ...] = ()
    if banks_raw is not None:
        if not isinstance(banks_raw, list) or not all(isinstance(b, str) and b for b in banks_raw):
            raise ConfigError(f"keys[{index}].banks must be a list of non-empty strings")
        banks = tuple(banks_raw)

    if all_banks and banks:
        raise ConfigError(f"keys[{index}] cannot set both all_banks and banks")
    if not all_banks and not banks:
        raise ConfigError(f"keys[{index}] must set all_banks: true or a non-empty banks list")

    secret = _resolve_secret_fields(block, f"keys[{index}]")
    return ApiKeySpec(id=key_id, name=name, secret=secret, all_banks=all_banks, banks=banks)


def parse_config_document(raw: Any) -> BankApiKeysConfig:
    """Parse and validate a loaded YAML document."""
    doc = _require_mapping(raw, "root")
    version = doc.get("version")
    if version != 1:
        raise ConfigError("version must be 1")

    admin = _parse_admin(doc.get("admin"))
    keys_raw = doc.get("keys", [])
    if keys_raw is None:
        keys_raw = []
    if not isinstance(keys_raw, list):
        raise ConfigError("keys must be a list")

    keys = tuple(_parse_key(entry, index) for index, entry in enumerate(keys_raw))
    ids = [key.id for key in keys]
    if len(set(ids)) != len(ids):
        raise ConfigError("duplicate key ids are not allowed")

    if admin is None and not keys:
        raise ConfigError("config must define admin and/or at least one key")

    return BankApiKeysConfig(admin=admin, keys=keys)


def load_config_file(path: Path) -> BankApiKeysConfig:
    """Load and validate configuration from a YAML file."""
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if raw is None:
        raise ConfigError(f"config file is empty: {path}")
    return parse_config_document(raw)


def _secret_matches(provided: str, configured: str) -> bool:
    if configured.startswith("hash:"):
        return verify_secret(provided, configured.removeprefix("hash:"))
    return provided == configured


def match_token(config: BankApiKeysConfig, token: str) -> AuthMatch | None:
    """Match a bearer token against admin and configured keys."""
    if config.admin is not None and token == config.admin.secret:
        return AuthMatch(key_id=ADMIN_KEY_ID, all_banks=True, banks=())

    for key in config.keys:
        if _secret_matches(token, key.secret):
            return AuthMatch(key_id=key.id, all_banks=key.all_banks, banks=key.banks)
    return None


def allowed_banks_for_key_id(config: BankApiKeysConfig, key_id: str) -> list[str] | None:
    """Return allowed bank ids for a key id, or None when unrestricted."""
    if key_id == ADMIN_KEY_ID:
        return None
    spec = config.keys_by_id.get(key_id)
    if spec is None:
        return []
    if spec.all_banks:
        return None
    return list(spec.banks)


class ConfigCache:
    """Hot-reload cache keyed on file mtime and reload interval."""

    def __init__(self, path: Path, reload_interval_seconds: int = DEFAULT_RELOAD_INTERVAL_SECONDS) -> None:
        self._path = path
        self._reload_interval_seconds = max(reload_interval_seconds, 0)
        self._config: BankApiKeysConfig | None = None
        self._mtime_ns: int | None = None
        self._last_checked_monotonic: float = 0.0

    @property
    def path(self) -> Path:
        return self._path

    def get(self) -> BankApiKeysConfig:
        """Return cached config, reloading when the file changes."""
        now = time.monotonic()
        should_check = (
            self._config is None
            or self._reload_interval_seconds == 0
            or (now - self._last_checked_monotonic) >= self._reload_interval_seconds
        )
        if not should_check:
            assert self._config is not None
            return self._config

        self._last_checked_monotonic = now
        mtime_ns = self._path.stat().st_mtime_ns
        if self._config is not None and self._mtime_ns == mtime_ns:
            return self._config

        self._config = load_config_file(self._path)
        self._mtime_ns = mtime_ns
        return self._config

    def force_reload(self) -> BankApiKeysConfig:
        """Reload regardless of mtime / interval (used in tests)."""
        self._config = load_config_file(self._path)
        self._mtime_ns = self._path.stat().st_mtime_ns
        self._last_checked_monotonic = time.monotonic()
        return self._config
