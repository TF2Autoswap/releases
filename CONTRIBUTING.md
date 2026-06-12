# Contributing to TF2autoswap

Thank you for your interest in contributing! This document covers how to get involved effectively and what to expect from the process.

---

## Before You Contribute

Please read the following before opening an issue or pull request:

- [README](README.md) — project overview and usage
- [SECURITY.md](SECURITY.md) — vulnerability reporting
- [Code of Conduct](CODE_OF_CONDUCT.md) — community standards
- [AI Ethics & Assistance Policy](https://github.com/TF2Autoswap/main/wiki) — how AI tooling is used in this project

TF2autoswap is a non-commercial, community-focused tool. All contributions must remain consistent with that purpose.

---

## Reporting Bugs

Open an issue and include:

- Your operating system
- Python version (`python3 --version`)
- Steps to reproduce the problem
- What you expected to happen vs. what actually happened
- Any relevant error output (paste as text, not a screenshot)

Please check existing issues before opening a new one.

---

## Suggesting Features

Feature requests are welcome via GitHub Discussions or Issues. When suggesting something, please consider:

- Whether it fits the tool's scope (client-side cosmetic/weapon model swapping)
- Whether it could introduce any fairness or security concerns
- Whether it's achievable without breaking existing functionality

Features that could facilitate cheating, provide unfair advantages, or enable visual exploits will not be accepted. This includes anything that could function as a wallhack, hitbox indicator, or similar regardless of how it is framed.

---

## Pull Requests

1. Fork the repository and create a branch from `main`
2. Keep changes focused — one feature or fix per PR
3. Follow the existing code style (British English comments, descriptive naming)
4. Test your changes before submitting
5. Describe what your PR does and why in the description

All pull requests from first-time contributors require maintainer approval before running in CI. This is a standard security measure and not a reflection on your contribution.

---

## Code Style

- Python 3.8+ compatible
- British English in all comments, docstrings, and user-facing strings
- Descriptive variable and function names
- Inline comments for anything non-obvious
- No unnecessary dependencies

---

## Scope and Limitations

TF2autoswap outputs client-side VPK files and native addons compatible with the Casual Preloader. Contributions outside this scope — such as server-side modifications, injection tools, or anything touching VAC-protected processes — are out of scope and will be declined.

---

## Security

Do not report security vulnerabilities via public issues. See [SECURITY.md](SECURITY.md) for the responsible disclosure process.

---

## Licence

By contributing, you agree that your contributions will be licensed under the project's [GNU General Public Licence v3](License).
