"""QSS: form input widgets (line edit, spin box, combo box, check box, radio)."""

from __future__ import annotations

QSS = """
/* --- Line Edit --- */

QLineEdit {
    background-color: #FBFAF7;
    border: 1px solid #C9C5BB;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    color: #111318;
    selection-background-color: #C8E6D8;
    selection-color: #111318;
    min-width: 200px;
    min-height: 20px;
}

QLineEdit:focus {
    border-color: #008457;
}

QLineEdit:disabled {
    background-color: #E8E6E0;
    color: #95999E;
}

/* --- Spin Box --- */

QSpinBox {
    background-color: #FBFAF7;
    border: 1px solid #C9C5BB;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    color: #111318;
}

QSpinBox:focus {
    border-color: #008457;
}

QSpinBox::up-button, QSpinBox::down-button {
    background-color: transparent;
    border: none;
    width: 20px;
}

QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background-color: #D8EDE4;
}

QSpinBox::up-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid #62666B;
    width: 0;
    height: 0;
}

QSpinBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #62666B;
    width: 0;
    height: 0;
}

/* --- Combo Box --- */

QComboBox {
    background-color: #FBFAF7;
    border: 1px solid #C9C5BB;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    color: #111318;
    min-height: 20px;
}

QComboBox:focus {
    border-color: #008457;
}

QComboBox:hover {
    border-color: #008457;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    border: none;
    width: 24px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #62666B;
    width: 0;
    height: 0;
}

QComboBox QAbstractItemView {
    background-color: #FBFAF7;
    border: 1px solid #C9C5BB;
    border-radius: 6px;
    padding: 4px;
    selection-background-color: #D8EDE4;
    selection-color: #008457;
    outline: none;
}

QComboBox QAbstractItemView::item {
    padding: 6px 12px;
    border-radius: 4px;
    min-height: 24px;
}

/* --- Check Box --- */

QCheckBox {
    spacing: 8px;
    font-size: 13px;
    color: #111318;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #C9C5BB;
    border-radius: 4px;
    background-color: #FBFAF7;
}

QCheckBox::indicator:hover {
    border-color: #008457;
}

QCheckBox::indicator:checked {
    background-color: #008457;
    border-color: #008457;
    image: url(none);
    /* White checkmark via border trick */
    border: 2px solid #008457;
    border-radius: 4px;
}

QCheckBox::indicator:disabled {
    background-color: #E8E6E0;
    border-color: #D5D1C8;
}

/* --- Radio Button --- */

QRadioButton {
    spacing: 8px;
    font-size: 13px;
    color: #111318;
}

QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #C9C5BB;
    border-radius: 9px;
    background-color: #FBFAF7;
}

QRadioButton::indicator:hover {
    border-color: #008457;
}

QRadioButton::indicator:checked {
    background-color: #FBFAF7;
    border: 5px solid #008457;
    border-radius: 9px;
    width: 8px;
    height: 8px;
}
"""
