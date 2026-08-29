"""Tests for the hindsight-bank-api-keys CLI."""

from __future__ import annotations

import textwrap
from pathlib import Path

from hindsight_bank_api_keys.cli import build_parser, cmd_validate


def test_cli_validate_ok(tmp_path: Path) -> None:
    yaml_path = tmp_path / "keys.yaml"
    yaml_path.write_text(
        textwrap.dedent(
            """
            version: 1
            keys:
              - id: k
                name: K
                secret: s
                banks: [b]
            """
        ),
        encoding="utf-8",
    )
    parser = build_parser()
    args = parser.parse_args(["validate", str(yaml_path)])
    assert cmd_validate(args) == 0


def test_cli_validate_failure(tmp_path: Path) -> None:
    yaml_path = tmp_path / "bad.yaml"
    yaml_path.write_text("version: 2\n", encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(["validate", str(yaml_path)])
    assert cmd_validate(args) == 1
