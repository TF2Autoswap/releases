# Security Policy

## Supported Versions

Only the latest release of TF2autoswap receives security updates.

| Version | Supported |
|---|---|
| 4.6 (latest) | ✅ |
| < 4.6 | ❌ |

## Reporting a Vulnerability

If you find a security issue in TF2autoswap, please do not open a public GitHub issue.

Instead, report it directly via:

- **Steam:** https://steamcommunity.com/id/MelancholySky
- **Email:** melancholysky@outlook.com

Please include:
- A description of the vulnerability
- Steps to reproduce it
- Any potential impact you've identified

I'll aim to respond within 72 hours and will keep you updated on the fix timeline.
Once resolved, you'll be credited in the release notes unless you'd prefer to remain anonymous.

## Scope

TF2autoswap is a client-side modding tool that reads TF2's VPK files and writes
output files to the user's own machine. It does not:

- Connect to any external servers
- Transmit any user data
- Modify any game files permanently
- Require elevated permissions

The attack surface is intentionally minimal. The most likely security concerns
would relate to malformed input files or path traversal via custom import paths,
both of which are within scope for reporting.
