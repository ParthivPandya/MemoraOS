# Security Policy

## Supported versions

Only the latest 0.x release receives security fixes.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability reporting ("Security" tab → "Report a vulnerability") on this repository. Include a description, reproduction steps, the affected version, and impact. We aim to acknowledge within 5 working days and to publish a fix and advisory once a patch is available.

In scope: tenant/user isolation bypass, authentication/authorization flaws, injection (SQL, prompt-structure), data leakage through export/deletion/caches, secret handling. Out of scope: issues requiring local filesystem access to an unencrypted data directory (see [docs/SECURITY.md](docs/SECURITY.md) on encryption at rest), denial of service by unbounded local usage.

Design, controls and known limitations: [docs/SECURITY.md](docs/SECURITY.md).
