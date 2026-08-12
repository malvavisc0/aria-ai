"""Aria GUI theme.

Global QSS split across section modules so no single file exceeds the
600-line cap. ``STYLESHEET`` is the concatenated stylesheet applied in
``aria.gui.main()``.

Colour palette aligned with the Chainlit WebUI light theme (public/theme.json).
Design tokens:
    Primary     : #008457  (green, hsl 155 100% 26%)
    Background  : #F7F5F0  (warm off-white, hsl 45 18% 96%)
    Card        : #FBFAF7  (warm white, hsl 48 16% 98%)
    Border      : #C9C5BB  (warm gray, hsl 40 10% 78%)
    Text        : #111318  (near-black, hsl 210 6% 7%)
    Muted text  : #62666B  (warm gray, hsl 210 4% 40%)
    Accent      : #D8EDE4  (light green, hsl 155 32% 91%)
    Destructive : #E53E3E  (hsl 0 84% 60%)
    Font        : Geist Sans / Geist Mono (loaded via CSS in the WebUI)
"""

from aria.gui.theme import base, inputs, panes, states

STYLESHEET = "\n".join((base.QSS, inputs.QSS, panes.QSS, states.QSS))

__all__ = ["STYLESHEET"]
