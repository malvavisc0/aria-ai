"""QSS: base window chrome and buttons (theme/compose.py joins the sections)."""

from __future__ import annotations

QSS = r"""
/* --- Base & Window ---
 * Cool, light neutral palette with a single deep-teal accent reserved
 * for primary actions and active states. Green/amber/red are used only
 * for status. Design tokens inline; see theme/__init__.py.
 */

QWidget {
    font-size: 13px;
    color: #1D2733;
    background-color: #F4F5F7;
}

QMainWindow {
    background-color: #F4F5F7;
}

QMainWindow::separator {
    background: #C3CBD3;
    width: 1px;
    height: 1px;
}

/* --- Menu Bar --- */

QMenuBar {
    background-color: #F4F5F7;
    border-bottom: 1px solid #E2E5EA;
    padding: 2px 6px;
}

QMenuBar::item {
    padding: 6px 12px;
    border-radius: 6px;
}

QMenuBar::item:selected {
    background-color: #DCF3EF;
    color: #0F766E;
}

QMenu {
    background-color: #FFFFFF;
    border: 1px solid #E2E5EA;
    border-radius: 8px;
    padding: 4px;
}

QMenu::item {
    padding: 8px 24px 8px 12px;
    border-radius: 6px;
}

QMenu::item:selected {
    background-color: #E6F7F5;
    color: #0F766E;
}

QMenu::separator {
    height: 1px;
    background: #E2E5EA;
    margin: 4px 8px;
}

/* --- Status Bar --- */

QStatusBar {
    background-color: #E9ECF0;
    border-top: 1px solid #E2E5EA;
    color: #5E6C7A;
    font-size: 12px;
    padding: 2px 8px;
}

QStatusBar::item {
    border: none;
}

/* --- Tab Widget (underline-style navigation) --- */

QTabWidget::pane {
    border: 1px solid #E2E5EA;
    border-top: none;
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
    background-color: #FFFFFF;
    top: -1px;
}

QTabBar {
    background: transparent;
}

QTabBar::tab {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 10px 18px 12px 18px;
    margin-right: 6px;
    font-weight: 600;
    font-size: 13px;
    color: #64748B;
}

QTabBar::tab:selected {
    color: #0F766E;
    border-bottom: 2px solid #0F766E;
}

QTabBar::tab:hover:!selected {
    color: #1D2733;
}

/* --- Group Box (card-style section) --- */

QGroupBox {
    font-weight: 600;
    font-size: 12px;
    letter-spacing: 0.04em;
    color: #5E6C7A;
    border: 1px solid #E2E5EA;
    border-radius: 10px;
    margin-top: 14px;
    padding-top: 22px;
    background-color: #FFFFFF;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 16px;
    padding: 0 8px;
    background-color: #FFFFFF;
    color: #5E6C7A;
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
    background-color: #FFFFFF;
    border: 1px solid #DCE1E8;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 500;
    color: #1D2733;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #F1F3F6;
    border-color: #8CD4CB;
    color: #0F766E;
}

QPushButton:pressed {
    background-color: #E6E9EE;
    border-color: #0F766E;
    color: #0B5E57;
}

QPushButton:disabled {
    background-color: #EEF1F4;
    border-color: #E2E5EA;
    color: #9AA5B1;
}

QPushButton:focus {
    outline: none;
    border-color: #0F766E;
}

QPushButton[primary="true"] {
    background-color: #0F766E;
    border-color: #0F766E;
    color: #FFFFFF;
}

QPushButton[primary="true"]:hover {
    background-color: #115E59;
    border-color: #115E59;
}

QPushButton[primary="true"]:pressed {
    background-color: #134E4A;
    border-color: #134E4A;
}

QPushButton[primary="true"]:disabled {
    background-color: #A6CCC7;
    border-color: #A6CCC7;
    color: #FFFFFF;
}

QPushButton[danger="true"] {
    background-color: #FFFFFF;
    border-color: #DC2626;
    color: #DC2626;
}

QPushButton[danger="true"]:hover {
    background-color: #FDECEB;
    border-color: #DC2626;
    color: #DC2626;
}

QPushButton[warning="true"] {
    background-color: #FFFFFF;
    border-color: #D97706;
    color: #B45309;
}

QPushButton[warning="true"]:hover {
    background-color: #FEF3E2;
    border-color: #D97706;
    color: #B45309;
}

QPushButton[warning="true"]:disabled {
    background-color: #EEF1F4;
    border-color: #E2E5EA;
    color: #9AA5B1;
}
"""
