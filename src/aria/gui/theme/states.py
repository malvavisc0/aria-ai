"""QSS: dynamic state selectors applied via setProperty() from code."""

from __future__ import annotations

QSS = """
/* Status Badge */
QLabel[status="running"] {
    background-color: #008457;
    color: #FFFFFF;
    font-size: 13px;
    font-weight: 600;
    padding: 4px 12px 4px 28px;
    border-radius: 2px;
    min-width: 90px;
}

QLabel[status="warning"] {
    background-color: #D97706;
    color: #FFFFFF;
    font-size: 13px;
    font-weight: 600;
    padding: 4px 12px 4px 28px;
    border-radius: 2px;
    min-width: 90px;
}

QLabel[status="error"] {
    background-color: #E53E3E;
    color: #FFFFFF;
    font-size: 13px;
    font-weight: 600;
    padding: 4px 12px 4px 28px;
    border-radius: 2px;
    min-width: 90px;
}

QLabel[status="idle"] {
    background-color: #62666B;
    color: #FFFFFF;
    font-size: 13px;
    font-weight: 600;
    padding: 4px 12px 4px 28px;
    border-radius: 2px;
    min-width: 90px;
}

QLabel[status="success"] {
    color: #008457;
    font-weight: 600;
}

/* Password Strength */
QLabel[strength="weak"] {
    color: #E53E3E;
    font-weight: 600;
}

QLabel[strength="fair"] {
    color: #D97706;
    font-weight: 600;
}

QLabel[strength="strong"] {
    color: #008457;
    font-weight: 600;
}

QLabel[strength="none"] {
    color: transparent;
}

/* Muted form labels */
QLabel[muted="true"] {
    color: #62666B;
}

/* Connection status */
QLabel[connection="ok"] {
    color: #008457;
}

QLabel[connection="fail"] {
    color: #E53E3E;
}
"""
