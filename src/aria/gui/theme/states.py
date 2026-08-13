"""QSS: dynamic state selectors applied via setProperty() from code."""

from __future__ import annotations

QSS = r"""
/* Status pill — tinted capsule, state conveyed by colour AND text. */
QLabel[status="running"] {
    background-color: #E7F4EC;
    color: #15803D;
    font-size: 12px;
    font-weight: 600;
    padding: 5px 14px;
    border-radius: 999px;
}

QLabel[status="warning"] {
    background-color: #FDF3E3;
    color: #B45309;
    font-size: 12px;
    font-weight: 600;
    padding: 5px 14px;
    border-radius: 999px;
}

QLabel[status="error"] {
    background-color: #FDEBE9;
    color: #B91C1C;
    font-size: 12px;
    font-weight: 600;
    padding: 5px 14px;
    border-radius: 999px;
}

QLabel[status="idle"] {
    background-color: #EEF1F4;
    color: #64748B;
    font-size: 12px;
    font-weight: 600;
    padding: 5px 14px;
    border-radius: 999px;
}

QLabel[status="success"] {
    color: #0F766E;
    font-weight: 600;
}

/* Password Strength */
QLabel[strength="weak"] {
    color: #DC2626;
    font-weight: 600;
}

QLabel[strength="fair"] {
    color: #B45309;
    font-weight: 600;
}

QLabel[strength="strong"] {
    color: #15803D;
    font-weight: 600;
}

QLabel[strength="none"] {
    color: transparent;
}

/* Muted form labels */
QLabel[muted="true"] {
    color: #7A8794;
}

/* Connection status */
QLabel[connection="ok"] {
    color: #0F766E;
}

QLabel[connection="fail"] {
    color: #DC2626;
}
"""
