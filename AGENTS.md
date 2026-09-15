# AGENTS.md

## Project overview
This repository contains a Debian/Ubuntu VPS setup automation stack for Xray-based VPN services. The main entrypoints are shell scripts such as `setup.sh`, `update.sh`, and `speedtest.sh`.

## Operating constraints
- Treat this as a Linux system administration project.
- Most scripts expect to run as root on Debian or Ubuntu.
- Do not run full installer commands in this workspace unless the user explicitly asks for a live system change.
- Prefer non-destructive validation such as `bash -n` before claiming a script is valid.

## Coding expectations
- Keep shell scripts portable across Debian/Ubuntu bash environments.
- Prefer existing repo patterns and variables over inventing new conventions.
- Preserve logging/output style and Indonesian/English mixed user-facing text where already used.
- When editing install logic, prefer idempotent checks (`[ -f ... ]`, `command -v`, `systemctl is-enabled`) instead of unconditional reinstallation.

## Validation
Before finishing work on a shell script:
1. Run `bash -n setup.sh`
2. Run `bash -n update.sh`
3. Run `bash -n speedtest.sh`

If a script is unrelated to the requested task, do not modify it.

## Repository-specific notes
- `setup.sh` is the primary installer flow.
- `update.sh` is a hardened update/setup script with a log file in `/root/setup.log`.
- `speedtest.sh` is a focused shell utility with strict mode enabled.
- The project downloads resources from GitHub raw URLs and installs packages via `apt`, `curl`, and `wget`.

## Change guidance
- Keep edits targeted and minimal.
- If a bug requires a root-cause fix, confirm the failing behavior and implement the smallest safe fix.
- Prefer clear comments near custom logic instead of over-documenting obvious shell checks.
- Avoid committing or suggesting destructive commands like `rm -rf /` or broad OS resets.
