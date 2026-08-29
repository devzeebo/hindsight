"""Tests for extension authentication."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from hindsight_api.extensions import AuthenticationError
from hindsight_api.models import RequestContext

from hindsight_bank_api_keys.extension import BankApiKeysExtension


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "bank-api-keys.yaml"
    path.write_text(
        textwrap.dedent(
            """
            version: 1
            admin:
              secret: admin-token
            keys:
              - id: scoped
                name: Scoped
                secret: scoped-token
                banks: [allowed-bank]
              - id: wide
                name: Wide
                secret: wide-token
                all_banks: true
            """
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def extension(config_file: Path) -> BankApiKeysExtension:
    ext = BankApiKeysExtension({"config_path": str(config_file), "reload_interval_seconds": "0"})
    return ext


@pytest.mark.asyncio
async def test_admin_authenticates_with_full_access(extension: BankApiKeysExtension) -> None:
    ctx = RequestContext(api_key="admin-token")
    tenant = await extension.authenticate(ctx)
    assert tenant.schema_name
    assert ctx.api_key_id == "admin"
    assert ctx.allowed_bank_ids is None


@pytest.mark.asyncio
async def test_scoped_key_sets_allowed_banks(extension: BankApiKeysExtension) -> None:
    ctx = RequestContext(api_key="scoped-token")
    await extension.authenticate(ctx)
    assert ctx.api_key_id == "scoped"
    assert ctx.allowed_bank_ids == ["allowed-bank"]


@pytest.mark.asyncio
async def test_all_banks_key_has_no_allowlist(extension: BankApiKeysExtension) -> None:
    ctx = RequestContext(api_key="wide-token")
    await extension.authenticate(ctx)
    assert ctx.api_key_id == "wide"
    assert ctx.allowed_bank_ids is None


@pytest.mark.asyncio
async def test_invalid_key_rejected(extension: BankApiKeysExtension) -> None:
    ctx = RequestContext(api_key="nope")
    with pytest.raises(AuthenticationError, match="Invalid API key"):
        await extension.authenticate(ctx)


@pytest.mark.asyncio
async def test_missing_token_rejected(extension: BankApiKeysExtension) -> None:
    ctx = RequestContext()
    with pytest.raises(AuthenticationError, match="Missing Authorization"):
        await extension.authenticate(ctx)
