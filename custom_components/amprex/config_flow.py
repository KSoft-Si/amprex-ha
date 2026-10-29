"""Config flow: paste the pairing code from the amprex Web UI."""

from __future__ import annotations

import asyncio
import logging
import ssl
from collections.abc import Mapping
from typing import Any

import aiomqtt
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from . import protocol
from .const import (
    CONF_ADDRESS,
    CONF_CERTIFICATE,
    CONF_CONTROLLER_ID,
    CONF_HOST,
    CONF_PAIRING_CODE,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    DOMAIN,
)
from .pairing import InvalidPairingCode, Pairing, build_tls_context, decode_pairing_code

_LOGGER = logging.getLogger(__name__)
_TEST_TIMEOUT_S = 15


class _FlowError(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _schema(defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_PAIRING_CODE): str,
            vol.Optional(CONF_ADDRESS, default=defaults.get(CONF_ADDRESS, "")): str,
        }
    )


def _entry_data(pairing: Pairing, address: str) -> dict[str, Any]:
    return {
        CONF_CONTROLLER_ID: pairing.controller_id,
        CONF_HOST: pairing.host,
        CONF_PORT: pairing.port,
        CONF_USERNAME: pairing.username,
        CONF_PASSWORD: pairing.password,
        CONF_CERTIFICATE: pairing.server_certificate_pem,
        CONF_ADDRESS: address,
    }


class AmprexConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _validate(
        self, user_input: dict[str, Any], *, new_entry: bool = False
    ) -> tuple[Pairing, str]:
        try:
            pairing = decode_pairing_code(user_input[CONF_PAIRING_CODE])
        except InvalidPairingCode as exc:
            _LOGGER.debug("Invalid pairing code: %s", exc)
            raise _FlowError("invalid_pairing_code") from exc
        if new_entry:
            # Before connecting: one entry per controller.
            await self.async_set_unique_id(pairing.controller_id)
            self._abort_if_unique_id_configured()
        try:
            tls = await self.hass.async_add_executor_job(
                build_tls_context, pairing.server_certificate_pem, pairing.host
            )
        except InvalidPairingCode as exc:
            _LOGGER.debug("Invalid pairing code: %s", exc)
            raise _FlowError("invalid_pairing_code") from exc
        address = user_input.get(CONF_ADDRESS, "").strip()
        await self._test_connection(pairing, address or pairing.host, tls)
        return pairing, address

    async def _test_connection(
        self, pairing: Pairing, address: str, tls: ssl.SSLContext
    ) -> None:
        """Connect with the pinned certificate and wait for the manifest."""
        try:
            async with asyncio.timeout(_TEST_TIMEOUT_S):
                async with aiomqtt.Client(
                    hostname=address,
                    port=pairing.port,
                    username=pairing.username,
                    password=pairing.password,
                    identifier=f"ha-setup-{pairing.username}",
                    tls_context=tls,
                ) as client:
                    await client.subscribe(protocol.manifest_topic(pairing.controller_id))
                    async for message in client.messages:
                        payload = message.payload
                        if isinstance(payload, bytes | bytearray):
                            protocol.parse_manifest(bytes(payload), pairing.controller_id)
                            return
        except TimeoutError as exc:
            raise _FlowError("no_manifest") from exc
        except protocol.UnsupportedManifest as exc:
            _LOGGER.warning("amprex manifest not usable: %s", exc)
            raise _FlowError("unsupported_manifest") from exc
        except aiomqtt.MqttError as exc:
            if protocol.is_auth_failure(exc):
                raise _FlowError("invalid_auth") from exc
            if isinstance(exc.__cause__, ssl.SSLError) or "certificate" in str(exc).lower():
                raise _FlowError("tls_error") from exc
            _LOGGER.debug("amprex connection test failed: %s", exc)
            raise _FlowError("cannot_connect") from exc

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                pairing, address = await self._validate(user_input, new_entry=True)
            except _FlowError as error:
                errors["base"] = error.key
            else:
                return self.async_create_entry(
                    title=f"amprex {pairing.host.removesuffix('.local')}",
                    data=_entry_data(pairing, address),
                )
        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input), errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The account was rotated or revoked: paste a new pairing code."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                pairing, address = await self._validate(user_input)
            except _FlowError as error:
                errors["base"] = error.key
            else:
                if pairing.controller_id != entry.data[CONF_CONTROLLER_ID]:
                    errors["base"] = "wrong_controller"
                else:
                    return self.async_update_reload_and_abort(
                        entry, data=_entry_data(pairing, address)
                    )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_schema(user_input or entry.data),
            errors=errors,
        )
