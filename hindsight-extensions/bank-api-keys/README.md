# Bank-Scoped API Keys Extension

YAML-configured bearer tokens for Hindsight with per-key bank access control.

## Overview

This extension replaces the built-in single-key [`ApiKeyTenantExtension`](../../hindsight-api-slim/hindsight_api/extensions/builtin/tenant.py) with multiple keys defined in a file. Each key can access one bank, many banks, or all banks.

It implements both:

- **`TenantExtension`** — authenticates `Authorization: Bearer <token>`
- **`OperationValidatorExtension`** — enforces bank allowlists on retain/recall/reflect and bank management APIs

No database tables. Edit the YAML file (or remount a ConfigMap) and changes are picked up automatically.

## Quick start

```bash
pip install ./hindsight-extensions/bank-api-keys
```

```bash
export HINDSIGHT_API_TENANT_EXTENSION=hindsight_bank_api_keys.extension:BankApiKeysExtension
export HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION=hindsight_bank_api_keys.extension:BankApiKeysExtension
export HINDSIGHT_API_BANK_API_KEYS_CONFIG=/etc/hindsight/bank-api-keys.yaml
export HINDSIGHT_API_BANK_API_KEYS_ADMIN_KEY=your-admin-secret
```

Point the control plane at the admin key via `HINDSIGHT_CP_DATAPLANE_API_KEY` (unchanged).

You must set **both** `HINDSIGHT_API_TENANT_EXTENSION` and `HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION` — tenant auth alone does not enforce bank scoping.

## Running with the official Docker image

This package is not baked into `ghcr.io/vectorize-io/hindsight`. Mount (or copy) it into the container and set the extension env vars. The stock image already includes PyYAML; **`bcrypt` does not**, so install it or use a thin image (below).

### Option A — volume mount (quick)

From the monorepo root (or any layout where you can mount this directory):

1. Copy [`examples/bank-api-keys.yaml`](examples/bank-api-keys.yaml) and edit secrets / bank ids.
2. Add volumes and env to your `hindsight` service:

```yaml
services:
  hindsight:
    image: ghcr.io/vectorize-io/hindsight:${HINDSIGHT_VERSION:-latest}
    ports:
      - "8888:8888"
      - "9999:9999"
    volumes:
      # Directory that contains the hindsight_bank_api_keys/ package
      - ./hindsight-extensions/bank-api-keys:/app/ext/bank-api-keys:ro
      - ./bank-api-keys.yaml:/etc/hindsight/bank-api-keys.yaml:ro
    environment:
      PYTHONPATH: /app/ext/bank-api-keys
      HINDSIGHT_API_TENANT_EXTENSION: hindsight_bank_api_keys.extension:BankApiKeysExtension
      HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION: hindsight_bank_api_keys.extension:BankApiKeysExtension
      HINDSIGHT_API_BANK_API_KEYS_CONFIG: /etc/hindsight/bank-api-keys.yaml
      HINDSIGHT_API_BANK_API_KEYS_ADMIN_KEY: your-admin-secret
      # Control plane proxies to the API with this bearer token — use the admin secret
      HINDSIGHT_CP_DATAPLANE_API_KEY: your-admin-secret
      # …your usual LLM / database vars…
    # bcrypt is required by the extension (secret_hash); install once at start
    command: >
      sh -c "pip install --quiet bcrypt &&
             exec hindsight-api"
```

If you already use a compose file under [`docker/docker-compose/`](../../docker/docker-compose/), add the same `volumes`, `environment`, and `command` to the existing `hindsight` service.

### Option B — thin image (recommended for production)

```dockerfile
FROM ghcr.io/vectorize-io/hindsight:latest
COPY hindsight-extensions/bank-api-keys /tmp/bank-api-keys
RUN pip install /tmp/bank-api-keys && rm -rf /tmp/bank-api-keys
```

Build and run with only the YAML mounted:

```bash
docker build -t hindsight-with-bank-keys -f Dockerfile .
```

```yaml
services:
  hindsight:
    image: hindsight-with-bank-keys
    volumes:
      - ./bank-api-keys.yaml:/etc/hindsight/bank-api-keys.yaml:ro
    environment:
      HINDSIGHT_API_TENANT_EXTENSION: hindsight_bank_api_keys.extension:BankApiKeysExtension
      HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION: hindsight_bank_api_keys.extension:BankApiKeysExtension
      HINDSIGHT_API_BANK_API_KEYS_CONFIG: /etc/hindsight/bank-api-keys.yaml
      HINDSIGHT_API_BANK_API_KEYS_ADMIN_KEY: your-admin-secret
      HINDSIGHT_CP_DATAPLANE_API_KEY: your-admin-secret
```

No `PYTHONPATH` or `pip install` at startup — the package and `bcrypt` are already in the image.

### Smoke test

```bash
# Admin — list all banks
curl -sS -H "Authorization: Bearer your-admin-secret" \
  http://localhost:8888/v1/default/banks

# Scoped key — only banks listed for that key
curl -sS -H "Authorization: Bearer hsak_replace_me" \
  -H "Content-Type: application/json" \
  http://localhost:8888/v1/default/banks/my-agent/memories/recall \
  -d '{"query":"hello"}'

# Scoped key on a bank it does not own → 403
curl -sS -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer hsak_replace_me" \
  http://localhost:8888/v1/default/banks/other-bank/stats
```

Control plane UI on port `9999` keeps working as long as `HINDSIGHT_CP_DATAPLANE_API_KEY` matches the admin secret.

Edits to the mounted YAML are picked up automatically (mtime check; default interval 30s via `HINDSIGHT_API_BANK_API_KEYS_RELOAD_INTERVAL_SECONDS`).

## YAML schema

See [`examples/bank-api-keys.yaml`](examples/bank-api-keys.yaml).

| Field | Description |
|-------|-------------|
| `version` | Must be `1` |
| `admin.secret` / `admin.secret_env` | Full-access admin key (all banks, can create banks) |
| `keys[].id` | Stable identifier (stored in `RequestContext.api_key_id`) |
| `keys[].name` | Human-readable label |
| `keys[].secret` | Plaintext secret (local dev only) |
| `keys[].secret_env` | Read secret from environment variable |
| `keys[].secret_hash` | bcrypt hash (production) |
| `keys[].banks` | List of allowed bank ids |
| `keys[].all_banks` | Unrestricted bank access (not admin — cannot create banks) |

Each key must specify exactly one secret source and either `banks` or `all_banks: true`.

## CLI helpers

```bash
# Validate config
hindsight-bank-api-keys validate ./bank-api-keys.yaml

# Hash a secret for secret_hash
hindsight-bank-api-keys hash 'my-secret'

# Generate a new hsak_ token + YAML snippet
hindsight-bank-api-keys generate --id ci-bot --name "CI" agent-a agent-b
hindsight-bank-api-keys generate --all-banks --id analytics
```

## Environment variables

| Variable | Description |
|----------|-------------|
| `HINDSIGHT_API_BANK_API_KEYS_CONFIG` | Path to YAML file (**required**) |
| `HINDSIGHT_API_BANK_API_KEYS_RELOAD_INTERVAL_SECONDS` | Mtime check interval (default `30`) |
| `HINDSIGHT_API_BANK_API_KEYS_ADMIN_KEY` | Typical admin secret referenced by `admin.secret_env` |
| `HINDSIGHT_API_TENANT_MCP_AUTH_DISABLED` | When `true`, skip MCP auth (same as built-in tenant extension) |

## Security notes

- Never commit plaintext `secret` values to git in production.
- Prefer `secret_env` for admin keys and `secret_hash` for scoped keys.
- Scoped keys cannot create new banks (`validate_create_bank` returns 403).
- Async worker tasks re-resolve bank access from `api_key_id` because task payloads do not carry `allowed_bank_ids`.

## Migration from ApiKeyTenantExtension

1. Add an `admin` block with the same secret you used for `HINDSIGHT_API_TENANT_API_KEY`.
2. Add scoped entries under `keys` as needed.
3. Set both extension env vars to `BankApiKeysExtension`.
4. Remove `HINDSIGHT_API_TENANT_API_KEY`.
