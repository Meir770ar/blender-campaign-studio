# Security

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private vulnerability reporting on this repository ("Security" tab, "Report a vulnerability"). You will get an acknowledgement within a week and a fix or a mitigation plan as soon as the report is confirmed.

## What this project handles

- **Credentials.** The skill never stores API keys, cookies or tokens. `connections.json` (git-ignored) holds file locations, hosts and model names; credentials remain with the clients that own them (an ElevenLabs env file, the Suno client profile, the HeyGen CLI profile, the OpenClaw auth store on its own host). Scripts are written so that secrets do not appear in job ledgers, receipts, logs or stdout.
- **Remote execution.** Some routes run commands over SSH (a render station, an OpenClaw gateway, a WAHA host). The scripts only call fixed commands with JSON payloads on stdin; user-supplied paths and prompts never enter a shell string. Review `provider_jobs.py`, `render_dispatch.py`, `station_archive.py`, `davinci_bridge.py` and `whatsapp_delivery.py` if you change any of these.
- **Spending.** Every paid generation is gated by a recorded approval with a cap; nothing retries automatically. A bug that bypasses `approve` / `approve-batch` or resubmits an `unknown` job is treated as a security issue.
- **Third-party code.** The OpenClaw patch package under `_verification/20260909-provider-expansion/` is applied to a gateway you own only through `activate_grok_patch.py --apply` with explicit approval evidence; it is never applied automatically.

## Supported versions

The `main` branch and the latest tagged release receive fixes.
