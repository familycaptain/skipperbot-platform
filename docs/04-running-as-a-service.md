# Running Skipper as a service (auto-start on boot)

By default you start Skipper by running the launcher (`skipper` / `skipper.sh` /
`skipper.bat`). That's fine for a laptop, but on an always-on box (a Pi, a mini
PC, a home server) you want Skipper to **come back on its own after a reboot or
power cut** — without anyone logging in to re-run the launcher.

That's what `skipper service` does. One command, same on every platform:

```
skipper service install      # install + enable, starts now and on every boot
skipper service status       # is it installed / running / healthy?
skipper service restart      # restart it (e.g. after 'skipper update' on native)
skipper service stop         # stop it (stays installed)
skipper service start        # start it again
skipper service uninstall    # remove it (your data and .env are untouched)
```

On Windows run it through the PowerShell launcher
(`skipper.bat service install` or
`powershell -ExecutionPolicy Bypass -File skipper.ps1 service install`).
On Linux/macOS use `./skipper.sh service install` (or just `skipper …`
if you ran `./skipper.sh install` to put it on your PATH).

The launcher picks the right mechanism automatically from **your saved runtime**
(`SKIPPER_RUNTIME` in `.env`, set during `skipper setup`) and your OS:

| OS | Docker runtime | Native runtime |
|---|---|---|
| **Linux** | systemd unit → `docker compose up -d` (+ `systemctl enable docker`) | systemd unit → `start_agent.sh`, restart-on-failure |
| **macOS** | launchd agent → waits for Docker, then `up -d` | launchd agent → `start_agent.sh`, `KeepAlive` |
| **Windows** | logon Scheduled Task → `docker compose up -d` | **NSSM** service → `start_agent.ps1` |
| **WSL** | = Windows Docker Desktop (see below) | systemd inside WSL **+** a Windows logon task |

For **Docker** runtimes, the compose stack already declares `restart: always`, so
the containers recover by themselves once Docker is running. The "service" there
is mostly about making sure **Docker itself starts at boot** and the stack is
`up`.

---

## Linux (systemd)

`skipper service install` writes `/etc/systemd/system/skipperbot.service` (needs
`sudo`), runs `systemctl enable --now`, and — for Docker — also
`systemctl enable docker` so the engine starts at boot.

- **Docker:** a `oneshot` unit, ordered `After=docker.service`, that runs
  `docker compose up -d` on boot and `docker compose down` on stop.
- **Native:** a `simple` unit that runs `start_agent.sh` as your user with
  `Restart=on-failure`. `start_agent.sh`'s exit codes are designed for this:
  `0` = clean stop (no restart), `42` = graceful restart (treated as failure, so
  systemd restarts it), anything else = crash → restart.

Manage it with either `skipper service …` or plain `systemctl … skipperbot`.
Logs: `journalctl -u skipperbot -f` (native) or `skipper logs` (Docker).

**Native PATH caveat.** systemd runs with a minimal `PATH`. The unit sets
`/usr/local/bin:/usr/bin:…`, which is enough for system-installed `node`/`npm`.
If you installed Node via **nvm** (under your home directory), it won't be on
that PATH — either install Node system-wide, or edit the `Environment=PATH=` line
in the unit to include your nvm `bin` directory, then
`sudo systemctl daemon-reload && skipper service restart`.

---

## macOS (launchd)

`skipper service install` writes
`~/Library/LaunchAgents/com.skipperbot.agent.plist` and loads it with
`launchctl`. Output goes to `logs/skipper-service.log` in the repo.

- **Docker:** runs at login, waits for Docker Desktop to be ready
  (`until docker info`), then `docker compose up -d`.
- **Native:** runs `start_agent.sh` with `KeepAlive` (relaunched if it exits).

**LaunchAgents run at _login_, not at boot.** For a headless Mac that should come
up unattended after a power cut, enable **automatic login**
(System Settings → Users & Groups → "Automatically log in as …") and, for Docker,
turn on Docker Desktop → Settings → General → "Start Docker Desktop when you log
in."

(If you need a true pre-login boot service, you can move the plist to
`/Library/LaunchDaemons` with `sudo` and add a `UserName` key — but for a home
server, auto-login + a LaunchAgent is simpler and is what `skipper service`
installs.)

---

## Windows

### Docker — logon Scheduled Task

`skipper service install` registers a **Scheduled Task** named `Skipperbot` that
runs `docker compose up -d` at logon. Combined with the stack's `restart: always`
and Docker Desktop's own autostart, that brings Skipper back after a reboot.

You must also enable **Docker Desktop → Settings → General → "Start Docker
Desktop when you sign in"** — the task needs Docker to be running to talk to. No
extra software is required for the Docker path.

### Native — NSSM service (prerequisite)

A native Windows service runs `start_agent.ps1` as a real Windows service via
**[NSSM](https://nssm.cc) (the Non-Sucking Service Manager)**. NSSM is a
**prerequisite you install yourself** — `skipper service` checks for it and stops
with instructions if it's missing:

```
choco install nssm
# or
winget install NSSM.NSSM
# or download https://nssm.cc/download, unzip, and put nssm.exe on your PATH
```

Once NSSM is on your `PATH`, `skipper service install` creates a service named
`Skipperbot` (auto-start, restart-on-exit), logging to
`logs\skipper-service.log`, and starts it. It shows up in `services.msc`.

**PATH caveat.** NSSM runs the service as **LocalSystem**, which uses the
*system* `PATH`. Make sure **Node, npm, and Python 3.12 are installed for all
users** (on the system PATH) — a per-user install won't be visible to the
service. Alternatively, open `services.msc` → Skipperbot → Log On, and set a
specific user account. (Reminder: a fully native Windows install also needs
pgvector, which has no prebuilt Windows binary — most Windows users should use
the **Docker** runtime instead; see the Path 2 callout in the README.)

---

## WSL

If you run Skipper **inside WSL with Docker Desktop** (WSL2 backend), that's
really the *Windows* Docker case — use `skipper service install` from the WSL
shell for the stack, and enable Docker Desktop autostart on Windows.

If you run Skipper **natively inside WSL** (Postgres/Python/Node in the distro),
`skipper service install` installs the same **systemd** unit as Linux. But a
service inside WSL only runs while the distro is up, so to start at **Windows**
boot you also need:

1. **systemd enabled in WSL** — add to `/etc/wsl.conf`:
   ```ini
   [boot]
   systemd=true
   ```
   then `wsl --shutdown` from Windows and reopen the distro.
2. **Windows to launch WSL at logon** — create a Scheduled Task (Task Scheduler)
   with an "At log on" trigger running:
   ```
   wsl -d <YourDistro> true
   ```
   Starting the distro triggers its systemd, which starts the Skipperbot unit.

---

## Deploy watcher (Docker only)

Separate from the agent service above, and separate from a **restart**. Know the
difference:

- **Restart** — the in-app restart button (and `POST /api/admin/restart`) drains
  in-flight work and bounces the agent on the **current code**. No pull, no
  rebuild. Fast. This is the everyday "kick it" action.
- **Deploy** — pulls the latest code **and rebuilds** so dependency changes take
  effect. Triggered deliberately: `skipper update` on the host, or
  `POST /api/admin/deploy` (used by the `deploy_skipper` flow).

The deploy watcher only matters for the **deploy** path under **Docker**: the
container can't `git pull` the host repo or recycle its own stack, so a small
**host-side** watcher (`scripts/deploy_watcher.sh`) does it when the agent drops
a `.deploy_pending` sentinel — running `git pull` then `docker compose up -d
--build` (same as `skipper update`). **Native installs don't need it**, and
without it a deploy request is just a plain container restart (no code update).

The watcher script is portable (bash + git + `docker compose`); only the way you
keep it running is per-OS:

| Host | How to run the watcher |
|------|------------------------|
| **Linux** | systemd unit — `skipper` offers to install it on a Docker host, or copy [`deploy/skipperbot-deploy-watcher.service.example`](../deploy/skipperbot-deploy-watcher.service.example) (edit the `CHANGE_ME` lines) to `/etc/systemd/system/`. |
| **macOS** | No systemd. Use a launchd agent that runs `scripts/deploy_watcher.sh`, or just `nohup scripts/deploy_watcher.sh &`. |
| **Windows** | No systemd/bash service. Run the script in Git-Bash/WSL via a Scheduled Task or NSSM. |
| **WSL** | Native-WSL-with-systemd → same unit as Linux. Docker-Desktop-backed WSL → run it under nohup or a Windows Scheduled Task. |
| **any** | Quick-and-dirty: `nohup scripts/deploy_watcher.sh >> /tmp/skipper-deploy-watcher.log 2>&1 &` |

It never touches the Docker socket — it runs `docker compose` as your user, so
that user just needs to be able to `git pull` the repo and run `docker compose`.

## Verifying

```
skipper service status     # shows the service state + a health probe
skipper status             # container/health only
```

`status` probes `http://localhost:<SKIPPERBOT_PORT>/api/onboarding/status`, so a
healthy install reports `HTTP 200`. After a reboot, give Docker (or the native
build step) a minute, then re-check.

## Uninstalling

`skipper service uninstall` stops and removes the unit / task / service. It does
**not** touch your `.env`, database, or volumes — you can still start Skipper
manually with the launcher afterward.
