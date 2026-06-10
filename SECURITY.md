# Security Policy

## Reporting a vulnerability

If you believe you've found a security vulnerability in Skipperbot, please
report it privately rather than opening a public GitHub issue.

**Preferred channel:** GitHub Security Advisories — open a private advisory
at `https://github.com/familycaptain/skipperbot-platform/security/advisories/new`.

**Alternative channel:** email `contact@familycaptain.com` with details.

Please include:

- A description of the vulnerability.
- Steps to reproduce, ideally with a minimal proof of concept.
- The affected version (`git rev-parse HEAD` for clones; release tag for releases).
- Any relevant logs or supporting evidence.

## Response

Maintainers will acknowledge receipt within **72 hours**. For confirmed
Critical or High severity issues, we target a patch within **30 days** of
acknowledgement. We'll keep you posted on progress and credit you in the
release notes if you'd like (or keep your report anonymous if you prefer).

## Severity definitions

- **Critical** — pre-auth remote code execution, secret exfiltration, full
  database read by an unauthenticated remote user.
- **High** — auth bypass, SQL injection, SSRF to internal services, default
  credentials shipping in code, an installed user's credentials being readable
  by another installed user on the same instance.
- **Medium** — cross-site scripting in user content, missing rate limits,
  weak CSRF protection, identity passed in URL query strings without an
  auth check.
- **Low** — verbose error messages, missing security headers, suboptimal
  cookie flags.

Critical and High issues are public-release blockers; Medium and Low are
tracked as regular issues with appropriate priority.

## Scope

This policy covers the `skipperbot-platform` repository. Each
`skipperbot-app-*` repository and each `skipperbot-<service>` companion
repository has its own `SECURITY.md` with the same template and process.

## Supported versions

During the pre-1.0 window, only the `main` branch is supported. Once we tag
v1.0, the most recent two minor versions receive security fixes; older
versions do not.
