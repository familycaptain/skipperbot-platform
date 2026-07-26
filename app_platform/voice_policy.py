"""Voice policy — whether an utterance ALSO goes to Discord. Pure decision, no I/O.

Kept separate from the speaking itself so it can be reasoned about and tested directly,
rather than rediscovered slightly differently inside every producer.

THE WEB IS NOT IN QUESTION
The console always receives. The consciousness log IS the record and the timeline is a
projection of it, so an utterance is there on the next load whether or not anything was
pushed — pushing to web only means "they are watching right now, put it on screen".
Discord is the opposite: a message not sent there never exists there.

So this module never decides whether someone gets a message. It decides whether a
SECOND copy is worth sending. Nothing here can lose anything.

WHY PREFERENCE AND NOT PRESENCE
Skipper cannot tell whether someone is "on Discord" — nothing tracks Discord presence,
and a DM waits until it is read regardless, so presence would not change the answer
even if we had it. Two things we CAN know settle it instead:

  * what the person told us — their primary surface. Somebody who lives in Discord
    should hear from Skipper there, not only when they happen to speak first.
  * what they are actually doing — a message sent FROM Discord makes Discord a live
    place to answer for a while, refreshed by each one. That is how a web-primary
    person gets answered where they wrote from, without being DM'd about everything
    that happens while they are away.

Voice is absent by design: the speaker is a SHARED device, so a voice turn is not
attributable to an individual and cannot be anyone's surface.
"""
# How long Discord stays a delivery target after someone sends a message FROM it,
# refreshed by each one. Its own constant, deliberately not shared with the greeting
# quiet-window even though both are currently 15 minutes: they answer different
# questions ("is Discord live for this person?" vs "have we only just spoken?"), and
# tuning one must not silently move the other.
DISCORD_ACTIVE_SECONDS = 15 * 60

WEB = "web"
DISCORD = "discord"



def plan_discord(*, primary_surface: str, discord_active: bool,
                 discord_linked: bool = True) -> bool:
    """Should this utterance ALSO go to Discord?

    The web console is not part of this question — it always receives, and always
    holds the complete record from every surface. This decides only whether an
    ADDITIONAL copy is worth sending, so no answer here can lose a message.

    primary_surface  — where this person says they mainly talk to Skipper.
    discord_active   — did they send something FROM Discord within the activity
                       window (DISCORD_ACTIVE_SECONDS, refreshed by each message)?
    discord_linked   — is Discord even wired up for them?

    Two rules, and the asymmetry is the point:
      * primary=discord — Discord IS their conversation, so it always receives. Waiting
        for a window would mean someone who lives in Discord hears nothing until they
        happen to speak first.
      * primary=web — Discord is a doorway, not a feed. It receives only while they are
        actually using it, so answering someone who wrote from Discord works, without
        DM-ing them about everything that happens while they are away.

    Deliberately NOT based on Discord presence: nothing tracks it, and a DM waits until
    it is read regardless. "Are they using Discord right now" is answerable from their
    own messages; "are they online" is not, and would not change the answer anyway.
    """
    if not discord_linked:
        return False
    if (primary_surface or "").strip().lower() == DISCORD:
        return True
    return bool(discord_active)



