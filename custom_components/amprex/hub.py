"""MQTT connection to one amprex controller.

Our own client, independent of Home Assistant's MQTT integration, so a
household can keep its own broker for HA. Subscribes only to what the
account's broker ACL grants and publishes only to its own command topics.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from collections.abc import Callable
from datetime import datetime, timezone

import aiomqtt

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from . import protocol
from .const import ACK_TIMEOUT_S, DOMAIN
from .pairing import Pairing

_LOGGER = logging.getLogger(__name__)

_RECONNECT_MIN_S = 5
_RECONNECT_MAX_S = 300


class AmprexAuthError(HomeAssistantError):
    """The broker refused the credential (rotated or revoked)."""


class AmprexCommandError(HomeAssistantError):
    """The controller rejected a command or did not answer."""


class AmprexHub:
    def __init__(
        self,
        hass: HomeAssistant,
        pairing: Pairing,
        address: str,
        tls_context: ssl.SSLContext,
        on_auth_failure: Callable[[], None],
    ) -> None:
        self.hass = hass
        self.pairing = pairing
        self._address = address
        self._tls = tls_context
        self._on_auth_failure = on_auth_failure
        self.controller_id = pairing.controller_id
        self.manifest: protocol.Manifest | None = None
        self.manifest_ready = asyncio.Event()
        self.online = False
        self.connected = False
        self.states: dict[str, protocol.State] = {}
        self._topic_keys: dict[str, str] = {}
        self._entity_listeners: dict[str, set[Callable[[], None]]] = {}
        self._manifest_listeners: set[Callable[[protocol.Manifest], None]] = set()
        self._acks: dict[str, asyncio.Future[protocol.Ack]] = {}
        self._client: aiomqtt.Client | None = None

    # ── Listeners ────────────────────────────────────────────────────────────

    @callback
    def listen_entity(self, key: str, update: Callable[[], None]) -> Callable[[], None]:
        self._entity_listeners.setdefault(key, set()).add(update)
        return lambda: self._entity_listeners.get(key, set()).discard(update)

    @callback
    def listen_manifest(self, update: Callable[[protocol.Manifest], None]) -> Callable[[], None]:
        self._manifest_listeners.add(update)
        return lambda: self._manifest_listeners.discard(update)

    @callback
    def notify_all(self) -> None:
        for listeners in list(self._entity_listeners.values()):
            for update in list(listeners):
                update()

    # ── Connection ───────────────────────────────────────────────────────────

    async def run(self) -> None:
        delay = _RECONNECT_MIN_S
        while True:
            try:
                await self._session()
                delay = _RECONNECT_MIN_S
            except aiomqtt.MqttError as exc:
                if protocol.is_auth_failure(exc):
                    _LOGGER.error("amprex %s refused the credential; re-pair", self.controller_id)
                    self._set_connected(False)
                    self._on_auth_failure()
                    return
                _LOGGER.warning("amprex %s connection lost: %s", self.controller_id, exc)
            self._set_connected(False)
            await asyncio.sleep(delay)
            delay = min(delay * 2, _RECONNECT_MAX_S)

    async def _session(self) -> None:
        controller = self.controller_id
        async with aiomqtt.Client(
            hostname=self._address,
            port=self.pairing.port,
            username=self.pairing.username,
            password=self.pairing.password,
            identifier=f"ha-{self.pairing.username}",
            tls_context=self._tls,
        ) as client:
            self._client = client
            try:
                await client.subscribe(protocol.availability_topic(controller), qos=1)
                await client.subscribe(protocol.manifest_topic(controller), qos=1)
                for state_filter in protocol.state_filters(controller):
                    await client.subscribe(state_filter, qos=0)
                await client.subscribe(
                    protocol.ack_filter(controller, self.pairing.account_id), qos=1
                )
                self._set_connected(True)
                async for message in client.messages:
                    payload = message.payload
                    if isinstance(payload, bytes | bytearray):
                        self._handle(str(message.topic), bytes(payload))
            finally:
                self._client = None

    @callback
    def _set_connected(self, connected: bool) -> None:
        self.connected = connected
        if not connected:
            self.online = False
            for future in self._acks.values():
                if not future.done():
                    future.set_exception(AmprexCommandError("Connection to amprex lost."))
        self.notify_all()

    @callback
    def _handle(self, topic: str, payload: bytes) -> None:
        controller = self.controller_id
        if topic == protocol.availability_topic(controller):
            self.online = payload.decode(errors="replace") == protocol.AVAILABILITY_ONLINE
            self.notify_all()
        elif topic == protocol.manifest_topic(controller):
            self._handle_manifest(payload)
        elif (key := self._topic_keys.get(topic)) is not None:
            state = protocol.parse_state(payload) if payload else None
            if state is None:
                self.states.pop(key, None)
            else:
                self.states[key] = state
            for update in list(self._entity_listeners.get(key, ())):
                update()
        elif (
            request_id := protocol.ack_request_id(controller, self.pairing.account_id, topic)
        ) is not None:
            ack = protocol.parse_ack(payload)
            future = self._acks.get(request_id)
            if ack is not None and future is not None and not future.done():
                future.set_result(ack)

    @callback
    def _handle_manifest(self, payload: bytes) -> None:
        try:
            manifest = protocol.parse_manifest(payload, self.controller_id)
        except protocol.UnsupportedManifest as exc:
            _LOGGER.error("amprex %s: %s", self.controller_id, exc)
            return
        self.manifest = manifest
        self._topic_keys = {
            entity.state_topic: entity.key
            for entity in manifest.entities
            if entity.state_topic is not None
        }
        self.manifest_ready.set()
        for update in list(self._manifest_listeners):
            update(manifest)
        self.notify_all()

    # ── Commands ─────────────────────────────────────────────────────────────

    async def async_command(self, key: str, value: float | str | None = None) -> None:
        client = self._client
        if client is None or not self.online:
            raise AmprexCommandError("amprex is not connected.")
        request_id, payload = protocol.build_command(value, datetime.now(timezone.utc))
        future: asyncio.Future[protocol.Ack] = self.hass.loop.create_future()
        self._acks[request_id] = future
        try:
            await client.publish(
                protocol.command_topic(self.controller_id, self.pairing.account_id, key),
                payload,
                qos=1,
            )
            async with asyncio.timeout(ACK_TIMEOUT_S):
                ack = await future
        except TimeoutError as exc:
            raise AmprexCommandError("amprex did not answer the command.") from exc
        except aiomqtt.MqttError as exc:
            raise AmprexCommandError(f"Could not send the command: {exc}") from exc
        finally:
            self._acks.pop(request_id, None)
        if not ack.accepted:
            raise AmprexCommandError(
                translation_domain=DOMAIN,
                translation_key="command_rejected",
                translation_placeholders={
                    "reason": ack.reason or "rejected",
                    "detail": ack.detail or "",
                },
            )
