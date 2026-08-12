"""QSS: content panes, scrollbars, labels, dialogs, and the wizard."""

from __future__ import annotations

QSS = """
/* --- Plain Text Edit (Log/Output Panes) --- */

QPlainTextEdit {
    background-color: #F3F0EA;
    border: 1px solid #C9C5BB;
    border-radius: 8px;
    padding: 12px;
    font-size: 11px;
    color: #111318;
    selection-background-color: #C8E6D8;
}

QPlainTextEdit:focus {
    border-color: #008457;
}

QPlainTextEdit:disabled {
    background-color: #E8E6E0;
    color: #95999E;
}

/* --- Text Edit (Logs) --- */

QTextEdit {
    background-color: #F3F0EA;
    border: 1px solid #C9C5BB;
    border-radius: 8px;
    padding: 12px;
    font-size: 12px;
    color: #111318;
    selection-background-color: #C8E6D8;
}

QTextEdit:focus {
    border-color: #008457;
}

/* --- List Widget --- */

QListWidget {
    background-color: #FBFAF7;
    border: 1px solid #C9C5BB;
    border-radius: 8px;
    padding: 4px;
    outline: none;
}

QListWidget::item {
    padding: 8px 12px;
    border-radius: 4px;
    margin: 1px 0;
}

QListWidget::item:selected {
    background-color: #D8EDE4;
    color: #008457;
}

QListWidget::item:hover:!selected {
    background-color: #E8E6E0;
}

/* --- Scroll Area --- */

QScrollArea {
    border: none;
    background: transparent;
}

QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #C9C5BB;
    border-radius: 4px;
    min-height: 32px;
}

QScrollBar::handle:vertical:hover {
    background: #95999E;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    height: 0;
}

QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background: #C9C5BB;
    border-radius: 4px;
    min-width: 32px;
}

QScrollBar::handle:horizontal:hover {
    background: #95999E;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
    width: 0;
}

/* --- Labels --- */

QLabel {
    background: transparent;
    color: #111318;
}

/* --- Tooltips --- */

QToolTip {
    background-color: #111318;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 12px;
}

/* --- Dialog --- */

QDialog {
    background-color: #F7F5F0;
}

/* --- Message Box --- */

QMessageBox {
    background-color: #F7F5F0;
}

/* --- Wizard --- */

QWizard {
    background-color: #F7F5F0;
}

QWizardPage {
    background-color: #F7F5F0;
}

QWizardPage QLineEdit {
    min-width: 280px;
}

QDialog QLineEdit {
    min-width: 250px;
}
"""
