"""Tests for YAML config parsing and caching."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from hindsight_bank_api_keys.config import (
    ConfigCache,
    ConfigError,
    load_config_file,
    match_token,
    parse_config_document,
)
from hindsight_bank_api_keys.crypto import hash_secret, verify_secret


def test_hash_and_verify_roundtrip() -> None:
    secret = "hsak_test_secret_value"
    hashed = hash_secret(secret)
    assert verify_secret(secret, hashed)
    assert not verify_secret("wrong", hashed)


def test_parse_minimal_config() -> None:
    doc = {
        "version": 1,
        "admin": {"secret": "admin-secret"},
        "keys": [
            {"id": "a", "name": "A", "secret": "key-a", "banks": ["bank-1"]},
            {"id": "b", "name": "B", "secret": "key-b", "all_banks": True},
        ],
    }
    config = parse_config_document(doc)
    assert config.admin is not None
    assert config.admin.secret == "admin-secret"
    assert len(config.keys) == 2
    assert config.keys[0].banks == ("bank-1",)
    assert config.keys[1].all_banks is True


def test_duplicate_ids_rejected() -> None:
    doc = {
        "version": 1,
        "keys": [
            {"id": "dup", "name": "One", "secret": "s1", "banks": ["b1"]},
            {"id": "dup", "name": "Two", "secret": "s2", "banks": ["b2"]},
        ],
    }
    with pytest.raises(ConfigError, match="duplicate"):
        parse_config_document(doc)


def test_secret_env_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_KEY", "from-env")
    yaml_path = tmp_path / "keys.yaml"
    yaml_path.write_text(
        textwrap.dedent(
            """
            version: 1
            keys:
              - id: env-key
                name: Env
                secret_env: MY_KEY
                banks: [bank-a]
            """
        ),
        encoding="utf-8",
    )
    config = load_config_file(yaml_path)
    assert config.keys[0].secret == "from-env"


def test_secret_hash_auth() -> None:
    secret = "scoped-secret"
    doc = {
        "version": 1,
        "keys": [
            {
                "id": "hashed",
                "name": "Hashed",
                "secret_hash": hash_secret(secret),
                "banks": ["bank-x"],
            }
        ],
    }
    config = parse_config_document(doc)
    match = match_token(config, secret)
    assert match is not None
    assert match.key_id == "hashed"
    assert match.banks == ("bank-x",)
    assert match_token(config, "wrong") is None


def test_config_cache_hot_reload(tmp_path: Path) -> None:
    yaml_path = tmp_path / "keys.yaml"
    yaml_path.write_text(
        textwrap.dedent(
            """
            version: 1
            keys:
              - id: v1
                name: V1
                secret: secret-v1
                banks: [b1]
            """
        ),
        encoding="utf-8",
    )
    cache = ConfigCache(yaml_path, reload_interval_seconds=0)
    first = cache.get()
    assert first.keys[0].id == "v1"

    yaml_path.write_text(
        textwrap.dedent(
            """
            version: 1
            keys:
              - id: v2
                name: V2
                secret: secret-v2
                banks: [b2]
            """
        ),
        encoding="utf-8",
    )
    second = cache.get()
    assert second.keys[0].id == "v2"


def test_missing_env_for_secret_env(tmp_path: Path) -> None:
    yaml_path = tmp_path / "keys.yaml"
    yaml_path.write_text(
        textwrap.dedent(
            """
            version: 1
            keys:
              - id: missing
                name: Missing
                secret_env: NOT_SET_VAR
                banks: [b]
            """
        ),
        encoding="utf-8",
    )
    os.environ.pop("NOT_SET_VAR", None)
    with pytest.raises(ConfigError, match="NOT_SET_VAR"):
        load_config_file(yaml_path)
