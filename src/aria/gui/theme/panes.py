"""QSS: content panes, scrollbars, labels, dialogs, and the wizard."""

from __future__ import annotations

QSS = r"""
/* --- Plain Text Edit (Log/Output Panes) --- */

QPlainTextEdit {
    background-color: #F7F9FB;
    border: 1px solid #DCE1E8;
    border-radius: 8px;
    padding: 12px;
    font-family: "SF Mono", "JetBrains Mono", "Consolas", monospace;
    font-size: 12px;
    color: #1D2733;
    selection-background-color: #CFF0EA;
}

QPlainTextEdit:focus {
    border-color: #0F766E;
}

QPlainTextEdit:disabled {
    background-color: #EEF1F4;
    color: #9AA5B1;
}

/* --- Text Edit (Logs) --- */

QTextEdit {
    background-color: #F7F9FB;
    border: 1px solid #DCE1E8;
    border-radius: 8px;
    padding: 12px;
    font-family: "SF Mono", "JetBrains Mono", "Consolas", monospace;
    font-size: 12px;
    color: #1D2733;
    selection-background-color: #CFF0EA;
}

QTextEdit:focus {
    border-color: #0F766E;
}

/* --- List Widget --- */

QListWidget {
    background-color: #FFFFFF;
    border: 1px solid #DCE1E8;
    border-radius: 8px;
    padding: 4px;
    outline: none;
}

QListWidget::item {
    padding: 9px 12px;
    border-radius: 6px;
    margin: 1px 0;
}

QListWidget::item:selected {
    background-color: #E6F7F5;
    color: #0F766E;
}

QListWidget::item:hover:!selected {
    background-color: #F1F3F6;
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
    background: #C3CBD3;
    border-radius: 4px;
    min-height: 32px;
}

QScrollBar::handle:vertical:hover {
    background: #94A3B8;
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
    background: #C3CBD3;
    border-radius: 4px;
    min-width: 32px;
}

QScrollBar::handle:horizontal:hover {
    background: #94A3B8;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
    width: 0;
}

/* --- Labels --- */

QLabel {
    background: transparent;
    color: #1D2733;
}

QLabel[href="true"] {
    color: #0F766E;
    text-decoration: underline;
}

/* --- Tooltips --- */

QToolTip {
    background-color: #1F2933;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 12px;
}

/* --- Dialog --- */

QDialog {
    background-color: #F4F5F7;
}

/* --- Message Box --- */

QMessageBox {
    background-color: #F4F5F7;
}

/* --- Wizard --- */

QWizard {
    background-color: #F4F5F7;
}

QWizardPage {
    background-color: #F4F5F7;
}

QWizardPage QLineEdit {
    min-width: 280px;
}

QDialog QLineEdit {
    min-width: 250px;
}
"""
