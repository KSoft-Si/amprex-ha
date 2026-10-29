"""Constants for the amprex integration."""

DOMAIN = "amprex"

CONF_PAIRING_CODE = "pairing_code"
CONF_ADDRESS = "address"
CONF_CONTROLLER_ID = "controller_id"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_CERTIFICATE = "server_certificate_pem"

# How long setup waits for the retained manifest before retrying later.
MANIFEST_TIMEOUT_S = 30
# How long a command waits for the controller's acknowledgement.
ACK_TIMEOUT_S = 10
# Entity availability is re-evaluated this often, so expired states go unavailable.
EXPIRY_CHECK_S = 30
