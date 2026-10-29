"""amprex HA bridge wire contract (`amprex/ha/v1/<controller_id>/`).

Mirrors `ksoft_common.ha_topics` / `ksoft_common.ha_contract` in ksoft-ems
(docs/HOME_ASSISTANT_INTEGRATION.md). No Home Assistant imports.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

TOPIC_ROOT = "amprex/ha/v1"
SUPPORTED_SCHEMA_VERSION = 1
STATE_DOMAINS = ("telemetry", "site", "thermostat")
AVAILABILITY_ONLINE = "online"
PLATFORMS = ("sensor", "binary_sensor", "climate", "number", "select", "button")
_KEY_RE = re.compile(r"^[a-z0-9_]{1,64}$")
# CONNACK codes for a refused credential: MQTT 3.1.1 (4, 5) and MQTT 5 (134, 135).
_AUTH_FAILURE_CODES = {4, 5, 134, 135}


def is_auth_failure(exc: Exception) -> bool:
    """Whether a connect error means the broker refused the credential."""
    rc = getattr(exc, "rc", None)
    # paho ReasonCode (MQTT 5) carries the number in `.value` and has no __int__.
    code = getattr(rc, "value", rc)
    try:
        return code is not None and int(code) in _AUTH_FAILURE_CODES
    except (TypeError, ValueError):
        return False


def root(controller_id: str) -> str:
    return f"{TOPIC_ROOT}/{controller_id}"


def availability_topic(controller_id: str) -> str:
    return f"{root(controller_id)}/availability"


def manifest_topic(controller_id: str) -> str:
    return f"{root(controller_id)}/manifest"


def state_filters(controller_id: str) -> list[str]:
    # One filter per domain: the broker grants them per scope, never `state/#`.
    return [f"{root(controller_id)}/state/{domain}/#" for domain in STATE_DOMAINS]


def command_topic(controller_id: str, account_id: str, key: str) -> str:
    return f"{root(controller_id)}/account/{account_id}/command/{key}"


def ack_filter(controller_id: str, account_id: str) -> str:
    return f"{root(controller_id)}/account/{account_id}/command_ack/+"


def ack_request_id(controller_id: str, account_id: str, topic: str) -> str | None:
    prefix = f"{root(controller_id)}/account/{account_id}/command_ack/"
    return topic[len(prefix) :] if topic.startswith(prefix) else None


@dataclass(frozen=True)
class Entity:
    key: str
    platform: str
    name: str
    domain: str
    state_topic: str | None
    commandable: bool
    unit: str | None
    device_class: str | None
    state_class: str | None
    entity_category: str | None
    icon: str | None
    options: tuple[str, ...] | None
    min_value: float | None
    max_value: float | None
    step: float | None
    expire_after_s: int | None


@dataclass(frozen=True)
class Manifest:
    controller_id: str
    name: str
    manufacturer: str
    model: str
    sw_version: str | None
    entities: tuple[Entity, ...]

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(entity.key for entity in self.entities)


class UnsupportedManifest(ValueError):
    pass


def parse_manifest(payload: bytes, controller_id: str) -> Manifest:
    try:
        raw = json.loads(payload)
    except ValueError as exc:
        raise UnsupportedManifest("manifest is not JSON") from exc
    if not isinstance(raw, dict):
        raise UnsupportedManifest("manifest is not an object")
    if raw.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise UnsupportedManifest(
            f"manifest schema {raw.get('schema_version')!r} is not supported; update amprex-ha"
        )
    if raw.get("controller_id") != controller_id:
        raise UnsupportedManifest("manifest is for another controller")
    entities = []
    prefix = f"{root(controller_id)}/state/"
    for item in raw.get("entities") or []:
        entity = _entity(item, prefix)
        if entity is not None:
            entities.append(entity)
    return Manifest(
        controller_id=controller_id,
        name=str(raw.get("name") or "amprex"),
        manufacturer=str(raw.get("manufacturer") or "KSoft"),
        model=str(raw.get("model") or "amprex controller"),
        sw_version=raw.get("sw_version"),
        entities=tuple(entities),
    )


def _entity(item: Any, state_prefix: str) -> Entity | None:
    """One manifest entity; unknown platforms and bad entries are skipped."""
    if not isinstance(item, dict):
        return None
    key, platform = item.get("key"), item.get("platform")
    if not isinstance(key, str) or not _KEY_RE.fullmatch(key) or platform not in PLATFORMS:
        return None
    state_topic = item.get("state_topic")
    # Never subscribe outside this controller's state tree.
    if state_topic is not None and (
        not isinstance(state_topic, str) or not state_topic.startswith(state_prefix)
    ):
        return None
    options = item.get("options")
    return Entity(
        key=key,
        platform=platform,
        name=str(item.get("name") or key),
        domain=str(item.get("domain") or ""),
        state_topic=state_topic,
        commandable=bool(item.get("commandable")),
        unit=item.get("unit"),
        device_class=item.get("device_class"),
        state_class=item.get("state_class"),
        entity_category=item.get("entity_category"),
        icon=item.get("icon"),
        options=tuple(str(option) for option in options) if isinstance(options, list) else None,
        min_value=_number(item.get("min_value")),
        max_value=_number(item.get("max_value")),
        step=_number(item.get("step")),
        expire_after_s=int(item["expire_after_s"]) if isinstance(item.get("expire_after_s"), int) else None,
    )


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


@dataclass
class State:
    value: Any
    observed_at: datetime | None
    attributes: dict[str, Any] = field(default_factory=dict)

    def fresh(self, expire_after_s: int | None, now: datetime) -> bool:
        if expire_after_s is None:
            return True
        if self.observed_at is None:
            return False
        return now - self.observed_at <= timedelta(seconds=expire_after_s)


def parse_state(payload: bytes) -> State | None:
    try:
        raw = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    attributes = raw.get("attributes")
    return State(
        value=raw.get("value"),
        observed_at=parse_time(raw.get("observed_at")),
        attributes=attributes if isinstance(attributes, dict) else {},
    )


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def build_command(value: float | str | None, now: datetime | None = None) -> tuple[str, bytes]:
    """(request id, payload) of a fresh command."""
    request_id = str(uuid.uuid4())
    issued_at = (now or datetime.now(timezone.utc)).isoformat()
    body: dict[str, Any] = {"request_id": request_id, "issued_at": issued_at}
    if value is not None:
        body["value"] = value
    return request_id, json.dumps(body).encode()


@dataclass(frozen=True)
class Ack:
    accepted: bool
    reason: str | None
    detail: str | None
    retry_after_s: int | None


def parse_ack(payload: bytes) -> Ack | None:
    try:
        raw = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(raw, dict) or raw.get("status") not in ("accepted", "rejected"):
        return None
    retry = raw.get("retry_after_s")
    return Ack(
        accepted=raw["status"] == "accepted",
        reason=raw.get("reason"),
        detail=raw.get("detail"),
        retry_after_s=retry if isinstance(retry, int) else None,
    )
