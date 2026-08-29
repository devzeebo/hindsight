"""Tests for bank access enforcement."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from hindsight_api.extensions import (
    BankListContext,
    BankReadContext,
    BankReadOperation,
    CreateBankContext,
    RecallContext,
    RetainContext,
)
from hindsight_api.models import RequestContext

from hindsight_bank_api_keys.extension import BankApiKeysExtension


@pytest.fixture
def extension(tmp_path: Path) -> BankApiKeysExtension:
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
                banks: [bank-a, bank-b]
            """
        ),
        encoding="utf-8",
    )
    return BankApiKeysExtension({"config_path": str(path), "reload_interval_seconds": "0"})


async def _scoped_context(extension: BankApiKeysExtension) -> RequestContext:
    ctx = RequestContext(api_key="scoped-token")
    await extension.authenticate(ctx)
    return ctx


@pytest.mark.asyncio
async def test_retain_allowed_bank(extension: BankApiKeysExtension) -> None:
    ctx = await _scoped_context(extension)
    result = await extension.validate_retain(RetainContext(bank_id="bank-a", contents=[], request_context=ctx))
    assert result.allowed


@pytest.mark.asyncio
async def test_retain_denied_bank(extension: BankApiKeysExtension) -> None:
    ctx = await _scoped_context(extension)
    result = await extension.validate_retain(RetainContext(bank_id="bank-z", contents=[], request_context=ctx))
    assert not result.allowed
    assert result.status_code == 403


@pytest.mark.asyncio
async def test_recall_denied_bank(extension: BankApiKeysExtension) -> None:
    ctx = await _scoped_context(extension)
    result = await extension.validate_recall(RecallContext(bank_id="bank-z", query="hello", request_context=ctx))
    assert not result.allowed


@pytest.mark.asyncio
async def test_bank_read_denied(extension: BankApiKeysExtension) -> None:
    ctx = await _scoped_context(extension)
    result = await extension.validate_bank_read(
        BankReadContext(
            bank_id="other",
            operation=BankReadOperation.GET_BANK_STATS,
            request_context=ctx,
        )
    )
    assert not result.allowed


@pytest.mark.asyncio
async def test_create_bank_denied_for_scoped_key(extension: BankApiKeysExtension) -> None:
    ctx = await _scoped_context(extension)
    result = await extension.validate_create_bank(CreateBankContext(bank_id="new-bank", request_context=ctx))
    assert not result.allowed


@pytest.mark.asyncio
async def test_create_bank_allowed_for_admin(extension: BankApiKeysExtension) -> None:
    ctx = RequestContext(api_key="admin-token")
    await extension.authenticate(ctx)
    result = await extension.validate_create_bank(CreateBankContext(bank_id="new-bank", request_context=ctx))
    assert result.allowed


@pytest.mark.asyncio
async def test_filter_bank_list(extension: BankApiKeysExtension) -> None:
    ctx = await _scoped_context(extension)
    banks = [
        {"bank_id": "bank-a", "name": "A"},
        {"bank_id": "bank-b", "name": "B"},
        {"bank_id": "bank-c", "name": "C"},
    ]
    result = await extension.filter_bank_list(BankListContext(banks=banks, request_context=ctx))
    assert {bank["bank_id"] for bank in result.banks} == {"bank-a", "bank-b"}


@pytest.mark.asyncio
async def test_worker_replay_resolves_banks_by_api_key_id(extension: BankApiKeysExtension) -> None:
    ctx = RequestContext(internal=True, api_key_id="scoped")
    result = await extension.validate_recall(RecallContext(bank_id="bank-a", query="q", request_context=ctx))
    assert result.allowed

    denied = await extension.validate_recall(RecallContext(bank_id="bank-z", query="q", request_context=ctx))
    assert not denied.allowed
