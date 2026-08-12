"""QSS: base window chrome and buttons (theme/compose.py joins the sections)."""

from __future__ import annotations

QSS = """
/* --- Base & Window --- */

QWidget {
    font-size: 12px;
    color: #111318;
    background-color: #F7F5F0;
}

QMainWindow {
    background-color: #F7F5F0;
}

QMainWindow::separator {
    background: #C9C5BB;
    width: 1px;
    height: 1px;
}

/* --- Menu Bar --- */

QMenuBar {
    background-color: #F7F5F0;
    border-bottom: 1px solid #D5D1C8;
    padding: 2px 4px;
}

QMenuBar::item {
    padding: 6px 12px;
    border-radius: 4px;
}

QMenuBar::item:selected {
    background-color: #D8EDE4;
    color: #008457;
}

QMenu {
    background-color: #FBFAF7;
    border: 1px solid #C9C5BB;
    border-radius: 8px;
    padding: 4px;
}

QMenu::item {
    padding: 8px 24px 8px 12px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #D8EDE4;
    color: #008457;
}

QMenu::separator {
    height: 1px;
    background: #D5D1C8;
    margin: 4px 8px;
}

/* --- Status Bar --- */

QStatusBar {
    background-color: #E8E6E0;
    border-top: 1px solid #D5D1C8;
    color: #62666B;
    font-size: 12px;
    padding: 2px 8px;
}

QStatusBar::item {
    border: none;
}

/* --- Tab Widget --- */

QTabWidget::pane {
    border: 1px solid #C9C5BB;
    border-radius: 8px;
    background-color: #FBFAF7;
    top: -1px;
}

QTabBar {
    background: transparent;
}

QTabBar::tab {
    background-color: #E8E6E0;
    border: 1px solid #C9C5BB;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 8px 20px;
    margin-right: 2px;
    font-weight: 500;
    color: #62666B;
}

QTabBar::tab:selected {
    background-color: #FBFAF7;
    color: #008457;
    border-color: #C9C5BB;
    font-weight: 600;
}

QTabBar::tab:hover:!selected {
    background-color: #D5D1C8;
    color: #111318;
}

/* --- Group Box --- */

QGroupBox {
    font-weight: 600;
    font-size: 13px;
    color: #111318;
    border: 1px solid #C9C5BB;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 20px;
    background-color: #FBFAF7;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 8px;
    background-color: #FBFAF7;
    color: #111318;
}

QGroupBox::indicator {
    width: 16px;
    height: 16px;
}

/* --- Frames (transparent inside containers) --- */

QFrame {
    background: transparent;
}

/* --- Push Buttons --- */

QPushButton {
    background-color: #FBFAF7;
    border: 1px solid #C9C5BB;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 500;
    color: #111318;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #E8E6E0;
    border-color: #008457;
    color: #008457;
}

QPushButton:pressed {
    background-color: #D5D1C8;
    border-color: #005538;
    color: #005538;
}

QPushButton:disabled {
    background-color: #E8E6E0;
    border-color: #D5D1C8;
    color: #95999E;
}

QPushButton:focus {
    outline: none;
    border-color: #008457;
}

QPushButton[primary="true"] {
    background-color: #008457;
    border-color: #008457;
    color: #FFFFFF;
}

QPushButton[primary="true"]:hover {
    background-color: #006B47;
    border-color: #006B47;
}

QPushButton[primary="true"]:pressed {
    background-color: #005538;
    border-color: #005538;
}

QPushButton[primary="true"]:disabled {
    background-color: #66B899;
    border-color: #66B899;
    color: #FFFFFF;
}

QPushButton[danger="true"] {
    background-color: #FBFAF7;
    border-color: #E53E3E;
    color: #E53E3E;
}

QPushButton[danger="true"]:hover {
    background-color: #FDE8E8;
    border-color: #E53E3E;
    color: #E53E3E;
}

QPushButton[warning="true"] {
    background-color: #FBFAF7;
    border-color: #D97706;
    color: #D97706;
}

QPushButton[warning="true"]:hover {
    background-color: #FEF3C7;
    border-color: #D97706;
    color: #D97706;
}

QPushButton[warning="true"]:disabled {
    background-color: #E8E6E0;
    border-color: #D5D1C8;
    color: #95999E;
}
"""
