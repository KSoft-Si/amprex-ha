from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

CONTROLLER = "controller1"
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def _manifest(**overrides) -> bytes:
    state = f"amprex/ha/v1/{CONTROLLER}/state"
    body = {
        "schema_version": 1,
        "controller_id": CONTROLLER,
        "published_at": NOW.isoformat(),
        "entities": [
            {"key": "grid_power", "platform": "sensor", "name": "Grid power",
             "domain": "telemetry", "state_topic": f"{state}/telemetry/grid_power",
             "unit": "W", "expire_after_s": 120, "future_field": 1},
            {"key": "start_hold", "platform": "button", "name": "Start hold",
             "domain": "thermostat", "commandable": True},
            {"key": "sneaky", "platform": "sensor", "name": "x", "domain": "telemetry",
             "state_topic": "ems/controller1/system/telemetry/x"},
            {"key": "lawn", "platform": "lawn_mower", "name": "x", "domain": "site"},
            {"key": "Bad-Key", "platform": "sensor", "name": "x", "domain": "site"},
        ],
        **overrides,
    }
    return json.dumps(body).encode()


def test_manifest_keeps_only_safe_known_entities(protocol) -> None:
    manifest = protocol.parse_manifest(_manifest(), CONTROLLER)
    assert manifest.keys == {"grid_power", "start_hold"}


@pytest.mark.parametrize(
    "overrides", [{"schema_version": 2}, {"controller_id": "other"}, {"schema_version": None}]
)
def test_manifest_for_another_controller_or_schema_is_refused(protocol, overrides) -> None:
    with pytest.raises(protocol.UnsupportedManifest):
        protocol.parse_manifest(_manifest(**overrides), CONTROLLER)


def test_states_expire_after_the_manifest_limit(protocol) -> None:
    state = protocol.parse_state(
        json.dumps({"value": 1200.5, "observed_at": NOW.isoformat()}).encode()
    )
    assert state.fresh(120, NOW + timedelta(seconds=120))
    assert not state.fresh(120, NOW + timedelta(seconds=121))
    undated = protocol.parse_state(b'{"value": 1}')
    assert undated.fresh(None, NOW) and not undated.fresh(120, NOW)
    assert protocol.parse_state(b"garbage") is None


def test_commands_carry_a_fresh_request_id_and_timestamp(protocol) -> None:
    first, payload = protocol.build_command(21.5, NOW)
    second, _ = protocol.build_command(None, NOW)
    assert first != second
    assert json.loads(payload) == {"request_id": first, "issued_at": NOW.isoformat(), "value": 21.5}
    assert "value" not in json.loads(protocol.build_command(None, NOW)[1])


def test_subscriptions_stay_within_the_account_grants(protocol) -> None:
    filters = protocol.state_filters(CONTROLLER)
    assert f"amprex/ha/v1/{CONTROLLER}/state/#" not in filters
    assert all(f.startswith(f"amprex/ha/v1/{CONTROLLER}/state/") for f in filters)
    ack = protocol.ack_filter(CONTROLLER, "0123456789ab")
    topic = ack.replace("+", "req-1")
    assert protocol.ack_request_id(CONTROLLER, "0123456789ab", topic) == "req-1"
    assert protocol.ack_request_id(CONTROLLER, "ba9876543210", topic) is None


def test_refused_credentials_are_recognised_for_mqtt_5_reason_codes(protocol) -> None:
    class ReasonCode:  # paho's: the number is in .value, int() does not work
        def __init__(self, value: int) -> None:
            self.value = value

    class ConnectError(Exception):
        def __init__(self, rc) -> None:
            super().__init__("refused")
            self.rc = rc

    assert protocol.is_auth_failure(ConnectError(ReasonCode(135)))
    assert protocol.is_auth_failure(ConnectError(5))
    assert not protocol.is_auth_failure(ConnectError(ReasonCode(136)))  # server unavailable
    assert not protocol.is_auth_failure(Exception("no rc"))
