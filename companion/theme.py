"""Shared dark appearance for the desktop companion, settings and access dialogs."""
from PyQt6.QtGui import QColor, QPalette, QFontDatabase


def apply_theme(app):
    app.setStyle('Fusion')
    app.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont))
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: '#1c1c1e', QPalette.ColorRole.WindowText: '#f5f5f7',
        QPalette.ColorRole.Base: '#232326', QPalette.ColorRole.AlternateBase: '#2c2c2e',
        QPalette.ColorRole.Text: '#f5f5f7', QPalette.ColorRole.Button: '#343438',
        QPalette.ColorRole.ButtonText: '#f5f5f7', QPalette.ColorRole.Highlight: '#0a84ff',
        QPalette.ColorRole.HighlightedText: '#ffffff', QPalette.ColorRole.PlaceholderText: '#a0a0a8',
        QPalette.ColorRole.ToolTipBase: '#343438', QPalette.ColorRole.ToolTipText: '#f5f5f7',
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor('#8e8e98'))
    app.setPalette(palette)


MENU_STYLE = '''
QMenu {background:#2c2c2e;color:#f5f5f7;border:1px solid #505055;border-radius:12px;padding:6px;}
QMenu::item {padding:7px 16px;border-radius:6px;margin:1px 0;}
QMenu::item:selected {background:#0a84ff;color:white;}
QMenu::item:disabled {color:#8e8e98;}
QMenu::separator {height:1px;background:#48484d;margin:5px 9px;}
QToolTip {background:#343438;color:#f5f5f7;border:1px solid #505055;padding:6px;border-radius:6px;}
'''

PANEL_STYLE = '''
QMainWindow,QDialog,QWidget#settingsRoot {background:#1c1c1e;}
QWidget {color:#f5f5f7;font-size:13px;}
QFrame#settingsGroup {background:#2c2c2f;border:1px solid #414147;border-radius:12px;}
QFrame#settingsDivider {background:#414147;border:0;}
QLabel#settingsRowTitle {font-weight:600;color:#f5f5f7;}
QFrame#settingsSurface {background:#242426;border:1px solid #38383d;border-radius:18px;}
QLabel {background:transparent;color:#e5e5ea;}
QLabel#settingsPageTitle {font-size:20px;font-weight:600;color:#f5f5f7;}
QLabel#settingsBrand {font-size:24px;font-weight:600;color:#f5f5f7;}
QLabel#settingsSubtitle {font-size:12px;color:#a0a0a8;}
QPushButton#backToDesktop {background:#303034;border:1px solid #404046;border-radius:10px;padding:8px 16px;}
QListWidget#settingsNavigation {background:transparent;border:0;outline:0;font-size:13px;color:#c7c7cf;}
QListWidget#settingsNavigation::item {padding:10px 12px;margin:2px 0;border-radius:8px;}
QListWidget#settingsNavigation::item:selected {background:#35353a;color:#ffffff;font-weight:600;}
QListWidget#settingsNavigation::item:hover {background:#2b2b30;}
QListWidget#settingsNavigation::item:focus {border:1px solid #64aaff;}
QTabWidget::pane {border:0;background:transparent;}
QTabBar::tab {background:#2c2c2e;color:#c7c7cf;padding:9px 12px;border:0;}
QTabBar::tab:selected {background:#343438;color:white;border-bottom:2px solid #0a84ff;}
QPlainTextEdit,QLineEdit,QComboBox {background:#1e1e21;color:#f5f5f7;
    selection-background-color:#285f9e;selection-color:#ffffff;
    border:1px solid #48484d;border-radius:9px;padding:9px;}
QPushButton {background:#36363b;color:#f5f5f7;border:1px solid #414147;
    border-radius:9px;padding:7px 12px;min-height:22px;}
QPushButton:hover {background:#434349;border-color:#52525a;}
QPushButton:pressed {background:#29292e;}
QPushButton:disabled {background:#2a2a2e;color:#8e8e98;border-color:#3a3a40;}
QPushButton:focus,QComboBox:focus,QPlainTextEdit:focus,QLineEdit:focus {border:1px solid #8bc2ff;}
QPushButton#setupPrimary {background:#0a84ff;color:white;border:1px solid #3299ff;}
QPushButton#setupPrimary:hover {background:#2994ff;}
QComboBox::drop-down {border:0;width:26px;}
QComboBox QAbstractItemView {background:#2c2c2e;color:#f5f5f7;border:1px solid #505055;
    selection-background-color:#0a84ff;selection-color:white;outline:0;padding:4px;}
QCheckBox {color:#e5e5ea;spacing:8px;}
QCheckBox:focus {outline:1px solid #64aaff;}
QStatusBar {background:#1c1c1e;color:#a0a0a8;font-size:11px;border-top:1px solid #38383d;}
QScrollArea {background:transparent;border:0;}
QScrollArea > QWidget > QWidget {background:transparent;}
QScrollBar:vertical {background:transparent;width:7px;}
QScrollBar::handle:vertical {background:#63636b;border-radius:3px;min-height:24px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
''' + MENU_STYLE
