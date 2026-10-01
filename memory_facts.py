"""Rules shared by every fact extractor (chat turns, app records, thinking cycles).

Extraction exists to break a memory-worthy source into separate facts, each tagged and
recalled on its own. It is NOT meant to add information — every good fact comes from the
source. What it should never do is save the source back as a "fact" word for word: that is
the original memory twice, not a smaller piece of it.
"""
import re

_TOKEN_PREFIX = re.compile(r"^\s*\[[\d,]+ in / [\d,]+ out\]\s*")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def _words(text: str) -> list[str]:
    text = _TOKEN_PREFIX.sub("", text or "")
    return _WORD.findall(text.casefold())


def is_whole_restatement(fact: str, *originals: str) -> bool:
    """True when ``fact`` is identical to the ENTIRETY of one of the originals.

    "Identical" ignores case, whitespace, punctuation and quotes (and the debug token-count
    prefix some replies carry). A fact that is only part of an original — one of eight facts
    pulled out of a long paragraph — is not a restatement and is kept.
    """
    fw = _words(fact)
    if not fw:
        return False
    return any(fw == _words(o) for o in originals if o)
