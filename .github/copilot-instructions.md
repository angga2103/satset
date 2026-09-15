# Copilot instructions for this repository

This repository is a Debian/Ubuntu VPS automation project for Xray-based services. The primary files are shell scripts, not application code.

## Guardrails
- Assume the scripts are intended to run as root on Debian or Ubuntu.
- Prefer bash-compatible, idempotent logic.
- Do not propose or run destructive system-wide changes unless explicitly requested.
- Prefer validation via `bash -n` over blindly executing installer scripts.

## Repository patterns
- `setup.sh` is the main installer flow.
- `update.sh` performs setup/update work and writes logs to `/root/setup.log`.
- `speedtest.sh` uses `set -Eeuo pipefail` and strict error handling.
- Keep output consistent with the repo's existing shell script style.

## Validation checklist
When editing shell scripts, check:
- `bash -n setup.sh`
- `bash -n update.sh`
- `bash -n speedtest.sh`

Use the smallest possible test that confirms the changed behavior.
