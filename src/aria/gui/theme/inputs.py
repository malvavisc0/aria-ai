"""QSS: form input widgets (line edit, spin box, combo box, check box, radio)."""

from __future__ import annotations

QSS = r"""
/* --- Line Edit --- */

QLineEdit {
    background-color: #FFFFFF;
    border: 1px solid #DCE1E8;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: #1D2733;
    selection-background-color: #CFF0EA;
    selection-color: #0B5E57;
    min-width: 200px;
    min-height: 20px;
}

QLineEdit:focus {
    border-color: #0F766E;
}

QLineEdit:disabled {
    background-color: #EEF1F4;
    color: #9AA5B1;
}

/* --- Spin Box --- */

QSpinBox {
    background-color: #FFFFFF;
    border: 1px solid #DCE1E8;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: #1D2733;
    min-height: 20px;
}

QSpinBox:focus {
    border-color: #0F766E;
}

QSpinBox::up-button, QSpinBox::down-button {
    background-color: transparent;
    border: none;
    width: 20px;
}

QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background-color: #E6F7F5;
}

QSpinBox::up-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid #64748B;
    width: 0;
    height: 0;
}

QSpinBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #64748B;
    width: 0;
    height: 0;
}

/* --- Combo Box --- */

QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #DCE1E8;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: #1D2733;
    min-height: 20px;
}

QComboBox:focus {
    border-color: #0F766E;
}

QComboBox:hover {
    border-color: #8CD4CB;
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
    border-top: 5px solid #64748B;
    width: 0;
    height: 0;
}

QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #E2E5EA;
    border-radius: 8px;
    padding: 4px;
    selection-background-color: #E6F7F5;
    selection-color: #0F766E;
    outline: none;
}

QComboBox QAbstractItemView::item {
    padding: 7px 12px;
    border-radius: 6px;
    min-height: 24px;
}

/* --- Check Box --- */

QCheckBox {
    spacing: 8px;
    font-size: 13px;
    color: #1D2733;
}

QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border: 2px solid #C9D1D9;
    border-radius: 5px;
    background-color: #FFFFFF;
}

QCheckBox::indicator:hover {
    border-color: #0F766E;
}

QCheckBox::indicator:checked {
    background-color: #0F766E;
    border: 2px solid #0F766E;
    border-radius: 5px;
}

QCheckBox::indicator:disabled {
    background-color: #EEF1F4;
    border-color: #DCE1E8;
}

/* --- Radio Button --- */

QRadioButton {
    spacing: 8px;
    font-size: 13px;
    color: #1D2733;
}

QRadioButton::indicator {
    width: 17px;
    height: 17px;
    border: 2px solid #C9D1D9;
    border-radius: 9px;
    background-color: #FFFFFF;
}

QRadioButton::indicator:hover {
    border-color: #0F766E;
}

QRadioButton::indicator:checked {
    background-color: #FFFFFF;
    border: 5px solid #0F766E;
    border-radius: 9px;
    width: 9px;
    height: 9px;
}
"""
