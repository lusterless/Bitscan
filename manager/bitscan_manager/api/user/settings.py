"""/api/v1/settings (TS §6.2 L1126, §8.6 L1317–L1327; #68, #71).

GET: admin, session or API token. PATCH: admin with a TOTP-verified session,
refused for API tokens and during a long audit-sink outage (a sensitive
action, TS §6.2 L1084). A patch is any non-empty subset of the seven keys,
applied atomically or not at all; the answer holds all seven. No key can
disable inventory (TS §6.2 L1129).
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from bitscan_manager.api.problems import ABOUT_BLANK, Problem
from bitscan_manager.api.user import problem_responses
from bitscan_manager.auth.dependencies import require_role, require_totp_session
from bitscan_manager.auth.principal import Principal
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.repositories.settings import SettingsRepo
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services.settings import store
from bitscan_manager.services.users import TxAudit

router = APIRouter(prefix="/settings", tags=["settings"])
RUNTIME = Annotated[Runtime, Depends(get_runtime)]
_R = store.INT_RANGES


class SettingsBody(BaseModel):
    agent_token_ttl_days: int
    job_pull_seconds: int
    decommission_after_days: int
    redaction_patterns: list[str]
    max_parallel_plugins: int
    enrolment_alert_per_hour: int
    inventory_interval_s: int


class SettingsPatch(BaseModel):
    """Any non-empty subset of the seven keys; null is not a value."""

    model_config = ConfigDict(extra="forbid")
    agent_token_ttl_days: StrictInt | None = Field(
        default=None, ge=_R["agent_token_ttl_days"][0], le=_R["agent_token_ttl_days"][1]
    )
    job_pull_seconds: StrictInt | None = Field(
        default=None, ge=_R["job_pull_seconds"][0], le=_R["job_pull_seconds"][1]
    )
    decommission_after_days: StrictInt | None = Field(
        default=None,
        ge=_R["decommission_after_days"][0],
        le=_R["decommission_after_days"][1],
    )
    redaction_patterns: list[StrictStr] | None = Field(
        default=None, max_length=store.MAX_REDACTION_PATTERNS
    )
    max_parallel_plugins: StrictInt | None = Field(
        default=None, ge=_R["max_parallel_plugins"][0], le=_R["max_parallel_plugins"][1]
    )
    enrolment_alert_per_hour: StrictInt | None = Field(
        default=None,
        ge=_R["enrolment_alert_per_hour"][0],
        le=_R["enrolment_alert_per_hour"][1],
    )
    inventory_interval_s: StrictInt | None = Field(
        default=None, ge=_R["inventory_interval_s"][0], le=_R["inventory_interval_s"][1]
    )


def _body(settings: store.Settings) -> SettingsBody:
    return SettingsBody(**settings.as_dict())


def _unavailable() -> Problem:
    return Problem(503, ABOUT_BLANK, "The settings are unavailable.")


@router.get("", responses=problem_responses((401, 403, 429, 503)))
def get_settings(
    principal: Annotated[Principal, Depends(require_role("admin"))],
    runtime: RUNTIME,
) -> SettingsBody:
    try:
        with runtime.db.transaction() as tx:
            settings = store.read_settings(SettingsRepo(tx.conn))
    except store.SettingsUnavailable:
        raise _unavailable() from None
    return _body(settings)


@router.patch("", responses=problem_responses((401, 403, 429, 503)))
def patch_settings(
    body: SettingsPatch,
    principal: Annotated[Principal, Depends(require_totp_session())],
    runtime: RUNTIME,
) -> SettingsBody:
    sent = {key: getattr(body, key) for key in body.model_fields_set}
    nulls = sorted(key for key, value in sent.items() if value is None)
    if nulls:
        raise Problem(400, "invalid_request", f"Invalid request: body.{nulls[0]}")
    failure: Problem | None = None
    try:
        with runtime.db.transaction() as tx:
            tx.on_commit(runtime.sink_gate.wake)
            settings = store.apply_patch(
                SettingsRepo(tx.conn),
                TxAudit(PgAuditRepo(tx.conn), tx.on_commit),
                patch=sent,
                user_id=principal.user_id,
                now=runtime.clock.now(),
            )
    except store.SettingsInvalid as exc:
        where = "body" if exc.key is None else f"body.{exc.key}"
        failure = Problem(400, "invalid_request", f"Invalid request: {where}")
    except store.SettingsUnavailable:
        failure = _unavailable()
    if failure is not None:
        raise failure
    return _body(settings)
