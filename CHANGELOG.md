# Changelog

All notable changes to Skipperbot Platform are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] — 2026-10-01

### Before you update

- **Nothing to do by hand.** Run `skipper update`. No migrations, no new dependencies.

### Added

- **GPT-6.1 Sol.** OpenAI's successor to GPT-6 Sol, at the same price, is available in
  **Settings → Models**. GPT-6 Sol stays the default.

### Fixed

- **No more "welcome back" every 16 minutes.** A browser or device whose connection drops and
  reconnects every minute was greeted again every quarter hour, day and night, and those greetings
  pushed real conversation (including agent replies) out of the chat window on reload. Skipper now
  treats a reconnect within 15 minutes as the same visit and stays quiet.
- The project manager's saved state (`apps/goals/data/`) no longer shows up as an untracked folder
  in `git status`.

## [0.1.0] — 2026-09-30

The first numbered release of Skipperbot Platform. Earlier work reached `main` without release
notes; from here on, every promotion to `main` gets a version, a tag and an entry here.

### Before you update

- **Nothing to do by hand.** Run `skipper update` as usual. This release adds no database
  migrations and no new dependencies.
- **Your model choice is kept.** GPT-6 Sol and GPT-6 Luna are the new defaults for *new*
  installs. To switch an existing install, pick them in **Settings → Models**.

### Added

- **GPT-6 models.** `gpt-6-sol` (Smart) and `gpt-6-luna` (Fast) are available, and are the
  defaults on a new install.
- **Reasoning effort per tier.** Settings → Models lets you set the reasoning effort for the
  Smart and Fast tiers. Leave it on the default (medium) unless you have a reason to change it.
- **Shared chat threads with agents.** An app can register an external agent that joins your
  conversation with Skipper. Each message goes to one addressee, whether by replying to it,
  starting with `@name`, or answering an open question. A presence bar shows who is in the
  thread. Nothing changes until an app registers an agent.
- **Reply to a specific message.** Reply to any of Skipper's messages, including notification
  cards, to keep a thread straight.
- **Send a notification from outside Skipper.** Admins can call `POST /api/apps/notifications`
  to have Skipper tell someone something. The response says who was reached and who was missed,
  and a dry run checks reachability without sending anything.

### Changed

- **Voice is brief and calm.** Skipper gives the shortest answer possible ("Done."), doesn't
  repeat your question or offer more, and speaks in an ordinary, relaxed tone. During a lookup it
  says nothing itself; you hear a one-word "Checking." if the wait is noticeable.
- **OpenAI calls use the Responses API.** Other providers are unchanged.
- **Other providers' model lists are refreshed.** A model was added only where the vendor's docs
  and an independent registry agree.
- **Output limits leave room for reasoning,** so reasoning models no longer cut answers short.
- **Voice model settings work.** Settings → Voice model and Voice transcription model now take
  effect. Unused model settings were removed.
- **Skipper's own goals sort to the bottom** of the Goals overview.
- **`/api/health` reports the real version,** read from `pyproject.toml`, the version's only source.

### Fixed

- Focus items show their names, not internal IDs, and the focus strip updates as soon as a pinned
  item changes.
- A to-do added in conversation goes to the top of the list.
- Finishing a Trello-linked task ticks the card's "Mark Complete".
- The project manager can't be talked into inventing tasks, and scrum suggests the task you're
  already working on and quotes you only once.
- A failed model call says why, without echoing your request back.
- Compatibility with newer MCP SDK versions.
- Background jobs are held until they finish, so they can't be dropped partway through.

[Unreleased]: https://github.com/familycaptain/skipperbot-platform/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/familycaptain/skipperbot-platform/releases/tag/v0.1.1
[0.1.0]: https://github.com/familycaptain/skipperbot-platform/releases/tag/v0.1.0
