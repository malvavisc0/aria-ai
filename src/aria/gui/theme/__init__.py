"""Aria GUI theme.

Global QSS split across section modules so no single file exceeds the
600-line cap. ``STYLESHEET`` is the concatenated stylesheet applied in
``aria.gui.main()``.

Design tokens (light, cool neutral with a deep-teal accent):
    Primary     : #0F766E  (deep teal, hsl 174 76% 26%)   -- actions / active
    Surface     : #F4F5F7  (cool light grey)
    Card        : #FFFFFF  (white)
    Border      : #DCE1E8 / #E2E5EA  (cool grey)
    Border-...  : #8CD4CB  (teal tint on hover)
    Text        : #1D2733  (cool near-black)
    Muted text  : #5E6C7A / #7A8794
    Accent     : #E6F7F5 / #DCF3EF  (teal tints for hover/selection)
    Status      : running #15803D,   warning #B45309,
                  error   #B91C1C,   idle    #64748B
    Destructive : #DC2626
    Font        : Geist Sans (UI) / monospace (logs) via platform stack
"""

from aria.gui.theme import base, inputs, panes, states

STYLESHEET = "\n".join((base.QSS, inputs.QSS, panes.QSS, states.QSS))

__all__ = ["STYLESHEET"]
