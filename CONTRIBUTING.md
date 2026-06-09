# Contributing to Skipperbot

Thanks for your interest in contributing. Skipperbot is an early-stage
self-hosted project; bug reports, feature ideas, and small PRs are
especially welcome.

## Reporting bugs

Open an issue on the platform repo with:

- What you tried to do.
- What happened.
- What you expected.
- Your environment: OS, Python version, Postgres version, install path
  (Docker / native), platform version (`git rev-parse HEAD`).
- Logs if you have them — the agent writes to `logs/` by default.

## Proposing features

Open an issue tagged `enhancement`. Describe the user problem first, the
proposed solution second. We'd rather discuss the design before code lands.

## Proposing a new app

Optional apps typically live in their own `skipperbot-app-<name>` repos. To propose
one, open an issue tagged `app-proposal` with:

- The app's purpose in one sentence.
- The entity types it would own.
- The tools the agent would gain.
- The events it would emit + subscribe to.

If the proposal is accepted, the maintainers help bootstrap the repo and
add it to the official optional-app catalog in `docs/02-adding-apps.md`.

If you are building a new app, it usually will be a separate repo. Changes
in this repo are mainly for fixing or enhancing the core platform or one of
the core apps included here. If you want to add a new core app, please reach
out first so we can discuss the design and ownership model.

## Pull requests

For changes to the platform itself:

1. Fork `skipperbot-platform`, create a feature branch.
2. Make your change. Keep PRs focused — one logical change per PR.
3. Ensure the change does not break prior installations or existing data.
4. If there are automated tests for the area you changed, run them. Otherwise,
   verify the behavior manually.
5. Run the lint suite (`ruff check`, ESLint on the web side).
6. Make sure CI passes — the name-scrubber, timezone-guard, gitleaks, bandit,
   and other security checks must all be green.
7. Open a PR. Reference any related issue.

For changes to an app: if the app ships with the platform as one of the built-in apps,
PR goes to this repo. If it's a separately distributed app, PR goes to that app's own repo.

## Architecture rules — non-negotiable

These are the boundaries that keep the system maintainable:

1. **The platform must not depend on any specific app.** No
   `from apps.<name> import ...` anywhere in platform code.
2. **Apps may depend on the platform** through `platform.*` services and the
   event bus, but apps must not depend on each other.
3. **Per-app schema isolation:** if an app owns data, it lives in
   `app_<id>` Postgres schema. Platform-owned cross-cutting tables live
   in `public.*` and apps may read/write via platform services.
4. **No hardcoded family / personal names** in any source file.
5. **No hardcoded timezones.** Use `platform.time.get_timezone()`.
6. **No `cron` dependency.** Everything scheduled goes through the
   `schedules` app.
7. **Cross-platform:** changes must work on Linux, macOS, and Windows.

See [specs/APP_PACKAGES.md](specs/APP_PACKAGES.md) for full details.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).

## License

By contributing, you agree your contributions are licensed under the same
[MIT License](LICENSE) the project uses.
