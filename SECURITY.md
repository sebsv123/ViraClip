# Security Policy

We take the security of ViraClip seriously. Thank you for helping us keep it safe for the community.

## Supported Versions

ViraClip is in active development; security fixes are applied to the latest commit on `main`. We do not currently maintain LTS branches.

| Version           | Supported          |
|-------------------|--------------------|
| `main` (latest)   | ✅                 |
| Older commits     | ❌ (please update) |

## Reporting a Vulnerability

**Please do not file public GitHub issues for security problems.**

To report a vulnerability:

1. Open a private [Security Advisory](https://github.com/sebsv123/ViraClip/security/advisories/new) on GitHub, **or**
2. Email the maintainer directly (see the public profile of [@sebsv123](https://github.com/sebsv123)).

Please include:

- A description of the vulnerability and its potential impact
- Steps to reproduce, or a proof-of-concept
- Any suggested mitigations
- Whether you would like to be credited in the advisory

## What to Expect

| Stage              | Target SLA                                            |
|--------------------|-------------------------------------------------------|
| Acknowledgement    | 72 hours                                              |
| Initial assessment | 7 days                                                |
| Fix or mitigation  | 30 days for high/critical, best-effort for the rest   |
| Public disclosure  | Coordinated with the reporter after a fix is released |

We will keep you informed throughout the process and credit you in the release notes if you wish.

## Scope

In scope:

- The ViraClip backend, frontend, waitlist app, worker, and Docker images
- Authentication, authorisation, and session handling
- Stored or transmitted user data
- API endpoints and webhooks (e.g. Stripe)
- Build/CI pipeline configuration
- Documented configuration that leads to insecure defaults

Out of scope (please don't report):

- Findings that require local access to the host running ViraClip (treat self-hosted security as the operator's responsibility)
- Known limitations of third-party services we depend on (open the report with them instead)
- Denial of service through resource exhaustion on a self-hosted instance
- Vulnerabilities in unsupported, archived, or third-party forks
- Best-practice violations without a concrete attack scenario
- Issues only reproducible against highly outdated dependencies in a fork

## Operational Security Reminders

If you self-host ViraClip in production:

- **Never commit `.env`** — use the secrets store of your hosting platform.
- **Rotate `BACKEND_AUTH_SECRET`, `BETTER_AUTH_SECRET`, and Stripe keys** if you suspect they were exposed.
- **Restrict Postgres and Redis to the internal Docker network**; the bundled `docker-compose.yml` already does this — do not publish these ports to the public internet.
- **Run behind a reverse proxy with TLS** (`nginx/` provides a reference config).
- **Keep the host kernel and Docker engine patched.**

Thank you for helping make ViraClip safer.
