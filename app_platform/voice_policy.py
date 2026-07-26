"""Voice policy — WHERE an utterance should go. Pure decision, no I/O.

Skipper has one voice but several surfaces (the web desktop, Discord, push). Deciding
which ones to speak on is a policy question, and it is kept here — separate from the
speaking itself — so it can be reasoned about and tested directly instead of being
rediscovered inside twenty different producers.

THE ASYMMETRY THAT MAKES THIS TRACTABLE
The web desktop is not a delivery target in the way Discord is. The consciousness log
IS the record, and the web timeline is a projection of it, so an utterance shows up
there on the next load whether or not anything was ever pushed. Pushing to web means
only "they are watching right now, put it on screen immediately".

Discord is the opposite: a message not sent to Discord never exists there.

So the question is never "how do we make sure this is durable" (the log already did
that). It is "who is actually going to see this, and where".

THE RULE, IN HUMAN TERMS
If you want to reach someone: you speak where they are. Once they answer you, you keep
talking on the surface they answered on — you do not repeat yourself into a second
channel mid-conversation. If they have gone quiet for a while, you go back to reaching
out wherever they might be.

That "keep talking where they answered" is the LOCK, and it is what prevents the
half-conversation problem: mirroring Skipper's side into Discord while the person is
typing on the web would show, in Discord, only one side of a dialogue.

When nobody is connected at all — the common case — an utterance still needs somewhere
to land, and we do not know which surface they will come back to. The log covers the
web return; Discord covers the Discord return.
"""
from dataclasses import dataclass

# How long after someone speaks we keep addressing that same surface. Long enough to
# cover a real back-and-forth with thinking pauses, short enough that an abandoned
# conversation reverts to reaching out broadly.
LOCK_TTL_SECONDS = 30 * 60

WEB = "web"
DISCORD = "discord"


@dataclass(frozen=True)
class SurfacePlan:
    """Where one utterance goes. The log write is unconditional and not represented
    here — it always happens, which is exactly why `web_live` can be False without the
    person ever losing the message."""
    web_live: bool      # push it onto the screen now (they are watching)
    discord: bool       # actually send it to Discord (otherwise it is not there at all)
    push: bool          # pushover/FCM — a tap on the shoulder, not a delivery surface
    reason: str         # why, for logs and tests

    @property
    def surfaces(self) -> tuple:
        out = []
        if self.web_live:
            out.append(WEB)
        if self.discord:
            out.append(DISCORD)
        return tuple(out)


def plan_surfaces(*, on_web: bool, lock: "str | None", urgent: bool = False) -> SurfacePlan:
    """Decide where to speak.

    on_web  — is this person connected to the web desktop right now?
    lock    — the surface of their most recent inbound message if it is still within
              LOCK_TTL_SECONDS, else None. The caller applies the TTL; by the time it
              reaches here, a lock is by definition current.
    urgent  — worth interrupting someone who is not connected anywhere.
    """
    if lock == WEB:
        # Mid-conversation on the web. Do NOT also send to Discord: they are reading
        # here, and Discord would receive a monologue — only Skipper's half.
        return SurfacePlan(web_live=on_web, discord=False, push=False,
                           reason="locked to web by a recent reply")
    if lock == DISCORD:
        # Mid-conversation on Discord. The web timeline still records it (the log), so
        # nothing is lost by not pushing a live frame.
        return SurfacePlan(web_live=False, discord=True, push=False,
                           reason="locked to discord by a recent reply")
    if on_web:
        # No conversation in flight, but they are here. Putting it on their screen is
        # enough; a Discord copy would be a second notification for something they are
        # already looking at.
        return SurfacePlan(web_live=True, discord=False, push=False,
                           reason="present on web, no active conversation")
    # Nobody home — the common case for background thoughts. The log covers a web
    # return; Discord is the only way it exists if they come back there instead.
    return SurfacePlan(web_live=False, discord=True, push=bool(urgent),
                       reason="not connected — reach out where they may return")


def lock_from_last_inbound(surface: "str | None", age_seconds: "float | None") -> "str | None":
    """The conversation lock, or None if it has aged out / there is nothing to lock to.

    Normalises whatever surface string the log recorded; anything that is not a surface
    we can speak on cannot hold a lock (e.g. a voice session is its own channel).
    """
    if not surface or age_seconds is None or age_seconds > LOCK_TTL_SECONDS:
        return None
    s = str(surface).strip().lower()
    if s in (WEB, "desktop", "ui"):
        return WEB
    if s == DISCORD:
        return DISCORD
    return None
