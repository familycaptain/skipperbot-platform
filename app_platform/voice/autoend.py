"""Voice session auto-end policy — pure, dependency-free classifiers + config.

Extracted from the relay so it's testable without the whole voice stack. It decides
which finalized user transcripts are (a) silence-hallucinations / backchannel to
DROP, or (b) farewells that END the session (everything else is real speech), and
owns the inactivity-timeout knob. See ``relay.py`` for how these are wired in.

Background: server-VAD trips on silence/echo and Whisper then emits short
hallucinations ("you" / "thank you" / "bye"). Left unchecked each drew a spoken
reply and nothing timed the session out, so an empty room could churn forever.
"""
from __future__ import annotations

import os

# End the session after this many seconds with no SUBSTANTIVE turn (0 disables).
IDLE_TIMEOUT_S = float(os.getenv("VOICE_IDLE_TIMEOUT_S", "30"))
# End deterministically on a farewell rather than hoping the model calls the tool.
FAREWELL_END = os.getenv("VOICE_FAREWELL_END", "1") not in ("0", "false", "False")
# Drop silence-hallucination / backchannel turns instead of replying to them.
DROP_NOISE_TURNS = os.getenv("VOICE_DROP_NOISE_TURNS", "1") not in ("0", "false", "False")

# Normalized (lowercased, punctuation-stripped) utterances that END the session.
_FAREWELL_PHRASES = {
    "bye", "goodbye", "good bye", "bye bye", "byebye", "that's all", "thats all",
    "that's it", "thats it", "i'm done", "im done", "we're done", "were done",
    "stop", "stop listening", "nevermind", "never mind", "good night", "goodnight",
    "that'll be all", "thatll be all", "done", "that is all",
}
# Classic Whisper silence-hallucinations + pure backchannel — never a real turn.
_NOISE_PHRASES = {
    "", "you", "thank you", "thanks", "thank you very much", "thanks for watching",
    "uh", "um", "hmm", "mm", "mmhmm", "mm hmm", "you know",
}


def normalize_utt(text: str) -> str:
    """Lowercase; keep letters/digits/spaces/apostrophes; collapse whitespace."""
    kept = "".join(c for c in (text or "").lower() if c.isalnum() or c in " '")
    return " ".join(kept.split())


def is_farewell(text: str) -> bool:
    return normalize_utt(text) in _FAREWELL_PHRASES


def is_noise(text: str) -> bool:
    return normalize_utt(text) in _NOISE_PHRASES
