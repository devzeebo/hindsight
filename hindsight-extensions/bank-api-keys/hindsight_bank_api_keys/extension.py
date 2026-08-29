"""Bank-scoped API keys extension (tenant auth + operation validation)."""

from __future__ import annotations

import os
from pathlib import Path

from hindsight_api.config import get_config
from hindsight_api.extensions import (
    AuthenticationError,
    BankListContext,
    BankListResult,
    BankReadContext,
    BankWriteContext,
    ConsolidateContext,
    CreateBankContext,
    OperationValidatorExtension,
    RecallContext,
    ReflectContext,
    RetainContext,
    Tenant,
    TenantContext,
    TenantExtension,
    ValidationResult,
)
from hindsight_api.models import RequestContext

from hindsight_bank_api_keys.config import (
    DEFAULT_RELOAD_INTERVAL_SECONDS,
    AuthMatch,
    ConfigCache,
    ConfigError,
    allowed_banks_for_key_id,
    match_token,
)


class BankApiKeysExtension(TenantExtension, OperationValidatorExtension):
    """
    Authenticate bearer tokens from a YAML file and enforce bank-scoped access.

    Configure via:
        HINDSIGHT_API_TENANT_EXTENSION=hindsight_bank_api_keys.extension:BankApiKeysExtension
        HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION=hindsight_bank_api_keys.extension:BankApiKeysExtension
        HINDSIGHT_API_BANK_API_KEYS_CONFIG=/path/to/bank-api-keys.yaml
        HINDSIGHT_API_BANK_API_KEYS_RELOAD_INTERVAL_SECONDS=30
    """

    def __init__(self, config: dict[str, str]) -> None:
        super().__init__(config)
        config_path = config.get("config_path") or os.environ.get("HINDSIGHT_API_BANK_API_KEYS_CONFIG")
        if not config_path:
            raise ValueError("HINDSIGHT_API_BANK_API_KEYS_CONFIG is required")

        interval_raw = config.get("reload_interval_seconds") or os.environ.get(
            "HINDSIGHT_API_BANK_API_KEYS_RELOAD_INTERVAL_SECONDS", str(DEFAULT_RELOAD_INTERVAL_SECONDS)
        )
        try:
            reload_interval = int(interval_raw)
        except ValueError as exc:
            raise ValueError("HINDSIGHT_API_BANK_API_KEYS_RELOAD_INTERVAL_SECONDS must be an integer") from exc

        self._config_cache = ConfigCache(Path(config_path), reload_interval_seconds=reload_interval)
        self._schema = config.get("schema", get_config().database_schema)
        self._mcp_auth_disabled = config.get("mcp_auth_disabled", "").lower() in ("true", "1", "yes")

    async def on_startup(self) -> None:
        try:
            self._config_cache.force_reload()
        except ConfigError as exc:
            raise RuntimeError(f"Failed to load bank API keys config: {exc}") from exc

    async def authenticate(self, context: RequestContext) -> TenantContext:
        token = context.api_key
        if not token:
            raise AuthenticationError("Missing Authorization header. Expected: Bearer <api_key>")

        auth = self._authenticate_token(token)
        self._apply_auth_to_context(context, auth)
        return TenantContext(schema_name=self._schema)

    async def authenticate_mcp(self, context: RequestContext) -> TenantContext:
        if self._mcp_auth_disabled:
            return TenantContext(schema_name=self._schema)
        return await self.authenticate(context)

    async def list_tenants(self) -> list[Tenant]:
        return [Tenant(schema=self._schema)]

    def _authenticate_token(self, token: str) -> AuthMatch:
        try:
            config = self._config_cache.get()
        except ConfigError as exc:
            raise AuthenticationError(f"API key configuration error: {exc}") from exc

        match = match_token(config, token)
        if match is None:
            raise AuthenticationError("Invalid API key")
        return match

    @staticmethod
    def _apply_auth_to_context(context: RequestContext, auth: AuthMatch) -> None:
        context.api_key_id = auth.key_id
        if auth.all_banks:
            context.allowed_bank_ids = None
        else:
            context.allowed_bank_ids = list(auth.banks)

    def _resolve_allowed_banks(self, request_context: RequestContext) -> list[str] | None:
        """
        Return allowed bank ids, or None for unrestricted access.

        HTTP requests populate allowed_bank_ids during authenticate(). Worker replay
        only carries api_key_id in the task payload, so re-resolve from the YAML cache.
        """
        if request_context.allowed_bank_ids is not None:
            return request_context.allowed_bank_ids

        if request_context.internal and request_context.api_key_id:
            try:
                config = self._config_cache.get()
            except ConfigError:
                return []
            return allowed_banks_for_key_id(config, request_context.api_key_id)

        return None

    def _bank_allowed(self, bank_id: str, request_context: RequestContext) -> bool:
        allowed = self._resolve_allowed_banks(request_context)
        if allowed is None:
            return True
        return bank_id in allowed

    def _reject_bank(self, bank_id: str, request_context: RequestContext) -> ValidationResult:
        if self._bank_allowed(bank_id, request_context):
            return ValidationResult.accept()
        return ValidationResult.reject("Bank access denied", status_code=403)

    async def validate_retain(self, ctx: RetainContext) -> ValidationResult:
        return self._reject_bank(ctx.bank_id, ctx.request_context)

    async def validate_recall(self, ctx: RecallContext) -> ValidationResult:
        return self._reject_bank(ctx.bank_id, ctx.request_context)

    async def validate_reflect(self, ctx: ReflectContext) -> ValidationResult:
        return self._reject_bank(ctx.bank_id, ctx.request_context)

    async def validate_consolidate(self, ctx: ConsolidateContext) -> ValidationResult:
        return self._reject_bank(ctx.bank_id, ctx.request_context)

    async def validate_bank_read(self, ctx: BankReadContext) -> ValidationResult:
        return self._reject_bank(ctx.bank_id, ctx.request_context)

    async def validate_bank_write(self, ctx: BankWriteContext) -> ValidationResult:
        return self._reject_bank(ctx.bank_id, ctx.request_context)

    async def validate_create_bank(self, ctx: CreateBankContext) -> ValidationResult:
        allowed = self._resolve_allowed_banks(ctx.request_context)
        if allowed is None:
            return ValidationResult.accept()
        return ValidationResult.reject("Bank creation is not allowed for scoped API keys", status_code=403)

    async def filter_bank_list(self, ctx: BankListContext) -> BankListResult:
        allowed = self._resolve_allowed_banks(ctx.request_context)
        if allowed is None:
            return BankListResult(banks=ctx.banks)
        allowed_set = set(allowed)
        filtered = [bank for bank in ctx.banks if bank.get("bank_id") in allowed_set]
        return BankListResult(banks=filtered)
