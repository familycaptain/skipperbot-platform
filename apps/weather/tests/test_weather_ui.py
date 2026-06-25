"""Bound guard test for weather.current-conditions.location-input-comfortable-width (ev-46).

Offline / deterministic — a pure source assertion over apps/weather/ui/WeatherApp.jsx
(no browser, no network, no import of the app). It guards the Weather header's manual
location <input> width: the field must be comfortably wide (a Tailwind width utility no
narrower than w-56 / 14rem) and must NOT regress to the original narrow w-48 (12rem), while
keeping the pl-7 left padding that makes room for the Search icon. The LIVE behaviour
(typed entry no longer clipped, Go/Refresh unchanged) is exercised by the spec's acceptance
scenario; this test is the cheap, deterministic regression guard.
"""
import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_JSX = os.path.normpath(os.path.join(_HERE, "..", "ui", "WeatherApp.jsx"))

# Tailwind width utilities accepted by the spec (>= 14rem). Matches the spec's
# width-token-tolerant guard so the operator can pick w-56 | w-64 | w-72 without
# editing this test.
_ACCEPTED_WIDTHS = ("w-56", "w-64", "w-72")


def _location_input_classname():
    """Return the className string of the manual location override <input>, located
    by its stable placeholder 'City or postal,country'."""
    with open(_JSX, encoding="utf-8") as fh:
        src = fh.read()
    idx = src.find('placeholder="City or postal,country"')
    assert idx != -1, "could not find the location override <input> (placeholder changed?)"
    # Find the className attribute on the same <input ...> element (it follows the placeholder).
    m = re.search(r'className="([^"]*)"', src[idx:])
    assert m, "location <input> has no className attribute"
    return m.group(1)


class WeatherLocationInputWidth(unittest.TestCase):
    def test_input_is_comfortably_wide(self):
        cls = _location_input_classname()
        self.assertTrue(
            any(w in cls.split() for w in _ACCEPTED_WIDTHS),
            f"location input must use a widened width ({' | '.join(_ACCEPTED_WIDTHS)}); got: {cls!r}",
        )

    def test_input_did_not_regress_to_narrow(self):
        cls = _location_input_classname()
        self.assertNotIn(
            "w-48", cls.split(),
            "location input regressed to the original narrow w-48 (12rem)",
        )

    def test_search_icon_padding_retained(self):
        cls = _location_input_classname()
        self.assertIn(
            "pl-7", cls.split(),
            "pl-7 left padding (room for the Search icon) must be retained",
        )


if __name__ == "__main__":
    unittest.main()
