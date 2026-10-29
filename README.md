# amprex for Home Assistant

A community integration that connects Home Assistant (2026.10.0 or newer) to an amprex controller
over the controller's own MQTT broker. It installs from the Home Assistant
[Marketplace](https://www.home-assistant.io/integrations/marketplace/), which replaced HACS in
2026.11, or from HACS on 2026.10.

- **State:** system power totals, battery state of charge, the current electricity price,
  service status, and the thermostat (temperatures, targets, holds, away).
- **Control (v1):** the thermostat only — holds, away, comfort feedback and resuming the
  schedule. Every change goes through the controller's own validation and audit, and the
  controller's thermostat arbitration stays the only path to the heat pump.

The integration keeps its own MQTT connection, separate from Home Assistant's MQTT integration,
and builds every entity from the controller's published entity list (the *manifest*). New amprex
entities appear without a new release of this integration.

## Install

1. In Home Assistant, go to **Settings → Marketplace → Add from link** and enter
   `KSoft-Si/amprex-ha`. Adding a repository from a link needs a GitHub connection; the
   Marketplace asks for it. Open **amprex** and select **Install**. No restart is needed for a
   first install.
   On Home Assistant 2026.10, add `https://github.com/KSoft-Si/amprex-ha` in HACS as a custom
   repository (type *Integration*), install **amprex** and restart Home Assistant.
2. In the amprex Web UI, open **Settings → Home Assistant** and create a connection. Copy the
   pairing code. It is shown only once.
3. The setup dialog opens after the install (or use the button below, or
   **Settings → Devices & services → Add integration → amprex**). Paste the pairing code.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=amprex)

Updates appear under **Settings → Updates**. After an update, Home Assistant asks for a restart
through a repair.

If the `amprex-….local` name does not resolve from Home Assistant (common with Home Assistant in
Docker), also enter the controller's IP address. The connection is still verified against the
controller's pinned certificate and its `.local` name.

## Security

- The pairing code contains an MQTT credential for one connection and the broker's public
  certificate. Treat it like a password. The integration trusts only that certificate.
- The connection can only read the amprex HA topics and write its own command topic. It cannot
  reach device control or other connections.
- Revoke or rotate the connection in the amprex Web UI. After a rotation, Home Assistant asks
  for the new pairing code.

## Entities

| Entity | What it does |
| --- | --- |
| Thermostat (`climate`, one per zone in per-zone mode) | Current temperature and target; setting a target starts a hold for the selected hold duration |
| Hold scope / Hold target / Hold duration, Start hold | Same controls as the Web UI (defaults: whole house, 21 °C, 2 h) |
| Resume schedule | Ends the active holds for the selected scope |
| Away | Off, until you end it, or 1 day … 2 weeks |
| Too cold / Comfortable / Too warm | Comfort feedback for the selected scope |
| Sensors | Power totals, battery SoC, current price, thermostat state, hold end, comfort control, service status |

Commands time out after 10 s. If the controller refuses one, Home Assistant shows the reason
(for example `too_early` for feedback given too soon).

## Development

Releases: bump `version` in `custom_components/amprex/manifest.json` and publish a GitHub release
whose tag is exactly that version (for example `0.1.0`, no `v`). The Marketplace offers published
releases only, refuses an integration whose manifest version it cannot load, and reads the minimum
Home Assistant version from `hacs.json`. Mark test builds as GitHub pre-releases.

The wire contract is defined in the ksoft-ems repository
(`docs/HOME_ASSISTANT_INTEGRATION.md`, `ksoft_common.ha_contract`). `protocol.py` and
`pairing.py` have no Home Assistant imports and are tested on their own:

```bash
uv run --with pytest pytest -q
```
