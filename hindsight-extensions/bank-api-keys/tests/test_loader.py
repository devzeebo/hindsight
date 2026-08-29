"""Tests for extension loading via the Hindsight loader."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from hindsight_api.extensions import OperationValidatorExtension, TenantExtension, load_extension

from hindsight_bank_api_keys.extension import BankApiKeysExtension


def test_load_as_tenant_and_validator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "keys.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            version: 1
            admin:
              secret: admin
            keys:
              - id: k1
                name: K1
                secret: s1
                banks: [b1]
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HINDSIGHT_API_TENANT_EXTENSION", "hindsight_bank_api_keys.extension:BankApiKeysExtension")
    monkeypatch.setenv("HINDSIGHT_API_BANK_API_KEYS_CONFIG", str(config_path))

    tenant = load_extension("TENANT", TenantExtension)
    assert isinstance(tenant, BankApiKeysExtension)

    monkeypatch.setenv(
        "HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION",
        "hindsight_bank_api_keys.extension:BankApiKeysExtension",
    )
    validator = load_extension("OPERATION_VALIDATOR", OperationValidatorExtension)
    assert isinstance(validator, BankApiKeysExtension)
