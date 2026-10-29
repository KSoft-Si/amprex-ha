from __future__ import annotations

import base64
import json
import shutil
import socket
import ssl
import subprocess
import threading

import pytest

HOST = "amprex-123456789xyz.local"


def _code(**overrides) -> str:
    body = {
        "v": 1,
        "controller_id": "ABC-123456789xyz",
        "host": HOST,
        "port": 8883,
        "username": "integration-0123456789ab",
        "password": "secret",
        "server_certificate_pem": "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n",
        **overrides,
    }
    raw = json.dumps(body).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_decodes_the_web_ui_pairing_code(pairing) -> None:
    decoded = pairing.decode_pairing_code(f"  {_code()}\n")
    assert decoded.host == HOST and decoded.port == 8883
    assert decoded.account_id == "0123456789ab"


@pytest.mark.parametrize(
    "code",
    [
        "not base64 !!",
        base64.urlsafe_b64encode(b"[1]").decode(),
        _code(v=2),
        _code(host="evil.example.com"),
        _code(username="internal"),
        _code(port=0),
        _code(password=""),
        _code(server_certificate_pem="-----BEGIN PRIVATE KEY-----\n"),
    ],
)
def test_rejects_anything_else(pairing, code) -> None:
    with pytest.raises(pairing.InvalidPairingCode):
        pairing.decode_pairing_code(code)


@pytest.fixture
def certificates(tmp_path):
    if shutil.which("openssl") is None:
        pytest.skip("openssl not available")

    def make(name: str, host: str):
        key, cert = tmp_path / f"{name}.key", tmp_path / f"{name}.crt"
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
             "-keyout", str(key), "-out", str(cert), "-subj", f"/CN={host}",
             "-addext", f"subjectAltName=DNS:{host}"],
            check=True, capture_output=True,
        )
        return key, cert

    return make


def _serve(key, cert) -> int:
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert, key)
    listener = socket.create_server(("127.0.0.1", 0))

    def accept() -> None:
        connection, _ = listener.accept()
        try:
            with server_context.wrap_socket(connection, server_side=True):
                pass
        except (ssl.SSLError, OSError):
            pass
        finally:
            listener.close()

    threading.Thread(target=accept, daemon=True).start()
    return listener.getsockname()[1]


def _handshake(context, port: int) -> None:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        # Dial by IP: the context still verifies the pinned .local name.
        with context.wrap_socket(sock, server_hostname="127.0.0.1"):
            pass


def test_tls_trusts_only_the_pinned_certificate_for_the_lan_name(pairing, certificates) -> None:
    key, cert = certificates("broker", HOST)
    pinned = cert.read_text()

    _handshake(pairing.build_tls_context(pinned, HOST), _serve(key, cert))

    with pytest.raises(ssl.SSLCertVerificationError):
        _handshake(pairing.build_tls_context(pinned, "amprex-other.local"), _serve(key, cert))

    other_key, other_cert = certificates("impostor", HOST)
    with pytest.raises(ssl.SSLCertVerificationError):
        _handshake(pairing.build_tls_context(pinned, HOST), _serve(other_key, other_cert))
