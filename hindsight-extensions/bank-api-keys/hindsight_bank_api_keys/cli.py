"""CLI helpers for bank API keys configuration."""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

from hindsight_bank_api_keys.config import ConfigError, load_config_file
from hindsight_bank_api_keys.crypto import hash_secret

KEY_PREFIX = "hsak_"


def _generate_secret() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.file)
    try:
        load_config_file(path)
    except ConfigError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    print(f"ok: {path}")
    return 0


def cmd_hash(args: argparse.Namespace) -> int:
    secret = args.secret
    if secret is None:
        secret = sys.stdin.read().strip()
    if not secret:
        print("secret is required (argument or stdin)", file=sys.stderr)
        return 1
    print(hash_secret(secret))
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    secret = _generate_secret()
    hashed = hash_secret(secret)
    key_id = args.id or "generated-key"
    name = args.name or "Generated key"
    print("# Store the secret securely — it is shown only once.")
    print(f"secret: {secret}")
    print()
    print("yaml:")
    print(f"  - id: {key_id}")
    print(f"    name: {name}")
    print(f'    secret_hash: "{hashed}"')
    if args.banks:
        print(f"    banks: [{', '.join(args.banks)}]")
    elif args.all_banks:
        print("    all_banks: true")
    else:
        print("    banks: [my-bank]")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hindsight-bank-api-keys", description="Bank API keys config helpers")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="Validate a YAML config file")
    validate.add_argument("file", help="Path to bank-api-keys.yaml")
    validate.set_defaults(func=cmd_validate)

    hash_cmd = sub.add_parser("hash", help="Hash a secret for secret_hash")
    hash_cmd.add_argument("secret", nargs="?", help="Secret to hash (or read from stdin)")
    hash_cmd.set_defaults(func=cmd_hash)

    generate = sub.add_parser("generate", help="Generate a new hsak secret and YAML snippet")
    generate.add_argument("--id", help="Key id for the YAML snippet")
    generate.add_argument("--name", help="Display name for the YAML snippet")
    generate.add_argument("--all-banks", action="store_true", help="Emit all_banks: true")
    generate.add_argument("banks", nargs="*", help="Bank ids for the YAML snippet")
    generate.set_defaults(func=cmd_generate)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
