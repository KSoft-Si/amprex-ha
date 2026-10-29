"""Pairing code from the amprex Web UI (Settings → Home Assistant).

Unpadded base64url JSON with `"v": 1`: controller id, broker host
(`amprex-<suffix>.local`), port, MQTT username/password and the broker's
public certificate. No Home Assistant imports, so it is testable alone.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import ssl
from dataclasses import dataclass

PAIRING_VERSION = 1
_USERNAME_RE = re.compile(r"^integration-[0-9a-f]{12}$")
_HOST_RE = re.compile(r"^amprex-[a-z0-9]{1,12}\.local$")
_PEM_BEGIN = "-----BEGIN CERTIFICATE-----"


class InvalidPairingCode(ValueError):
    """The text is not a pairing code this integration understands."""


@dataclass(frozen=True)
class Pairing:
    controller_id: str
    host: str
    port: int
    username: str
    password: str
    server_certificate_pem: str

    @property
    def account_id(self) -> str:
        return self.username.removeprefix("integration-")


def decode_pairing_code(code: str) -> Pairing:
    text = "".join(code.split())
    try:
        raw = json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise InvalidPairingCode("not a pairing code") from exc
    if not isinstance(raw, dict):
        raise InvalidPairingCode("not a pairing code")
    if raw.get("v") != PAIRING_VERSION:
        raise InvalidPairingCode("unsupported pairing code version")
    try:
        pairing = Pairing(
            controller_id=_text(raw, "controller_id"),
            host=_text(raw, "host"),
            port=int(raw["port"]),
            username=_text(raw, "username"),
            password=_text(raw, "password"),
            server_certificate_pem=_text(raw, "server_certificate_pem"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidPairingCode("incomplete pairing code") from exc
    if not _HOST_RE.fullmatch(pairing.host):
        raise InvalidPairingCode("unexpected broker host")
    if not 1 <= pairing.port <= 65535:
        raise InvalidPairingCode("invalid port")
    if not _USERNAME_RE.fullmatch(pairing.username):
        raise InvalidPairingCode("unexpected username")
    pem = pairing.server_certificate_pem
    if not pem.lstrip().startswith(_PEM_BEGIN) or "PRIVATE KEY" in pem:
        raise InvalidPairingCode("missing broker certificate")
    return pairing


def _text(raw: dict, key: str) -> str:
    value = raw[key]
    if not isinstance(value, str) or not value:
        raise ValueError(key)
    return value


class _PinnedContext(ssl.SSLContext):
    """Verifies the pinned certificate for `expected_hostname`, whatever address we dial.

    Lets the user connect by IP when `.local` names do not resolve (for example
    Home Assistant in Docker) without weakening hostname verification.
    """

    expected_hostname: str

    def wrap_socket(self, sock, *args, server_hostname=None, **kwargs):  # type: ignore[override]
        return super().wrap_socket(
            sock, *args, server_hostname=self.expected_hostname, **kwargs
        )


def build_tls_context(certificate_pem: str, expected_hostname: str) -> ssl.SSLContext:
    """Trust exactly the pinned broker certificate (blocking: run in an executor)."""
    context = _PinnedContext(ssl.PROTOCOL_TLS_CLIENT)
    context.expected_hostname = expected_hostname
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    # The pinned (self-signed) leaf is the only trust anchor; no system CAs.
    context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    try:
        context.load_verify_locations(cadata=certificate_pem)
    except ssl.SSLError as exc:
        raise InvalidPairingCode("unreadable broker certificate") from exc
    return context
