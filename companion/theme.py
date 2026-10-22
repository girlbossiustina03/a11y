"""Explicit palette prevents native dark-mode colors leaking into custom light surfaces."""
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication


def apply_theme(app):
    app.setStyle('Fusion')
    palette = QPalette()
    roles = {QPalette.ColorRole.Window: '#f4f6f0', QPalette.ColorRole.WindowText: '#263a30',
             QPalette.ColorRole.Base: '#fffef9', QPalette.ColorRole.AlternateBase: '#eef3e9',
             QPalette.ColorRole.Text: '#263a30', QPalette.ColorRole.Button: '#edf3e8',
             QPalette.ColorRole.ButtonText: '#263a30', QPalette.ColorRole.Highlight: '#286b50',
             QPalette.ColorRole.HighlightedText: '#ffffff', QPalette.ColorRole.PlaceholderText: '#6c7c70',
             QPalette.ColorRole.ToolTipBase: '#fffef9', QPalette.ColorRole.ToolTipText: '#263a30'}
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor('#788278'))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor('#788278'))
    app.setPalette(palette)


PANEL_STYLE = '''
QMainWindow {background:#f5f6f0;}
QWidget#settingsRoot {background:#f5f6f0;}
QFrame#settingsSurface {background:#fffef9;border:1px solid #d0dacf;border-radius:18px;}
QLabel#settingsPageTitle {font-size:19px;font-weight:600;color:#25352f;}
QLabel#settingsBrand {font-size:24px;font-weight:700;color:#25352f;}
QLabel#settingsSubtitle {font-size:12px;color:#627267;}
QPushButton#backToDesktop {background:#fffef9;border:1px solid #c3d2c5;border-radius:11px;padding:10px 18px;}
QListWidget#settingsNavigation {background:transparent;border:0;outline:0;font-size:13px;color:#627267;}
QListWidget#settingsNavigation::item {padding:13px 12px;margin:3px 0;border-radius:9px;}
QListWidget#settingsNavigation::item:selected {background:#e4eddf;color:#254e38;font-weight:600;}
QListWidget#settingsNavigation::item:hover {background:#ebf0e6;}
QListWidget#settingsNavigation::item:focus {border:1px solid #326bb3;}
QWidget {color:#263a30;font-size:13px;}
QLabel {background:transparent;color:#263a30;}
QTabWidget::pane {border:0;background:transparent;}
QTabBar::tab {background:#e8eee3;color:#566a58;padding:11px 13px;border:0;}
QTabBar::tab:selected {background:#f4f6f0;color:#184c35;border-bottom:3px solid #2b7956;}
QPlainTextEdit,QLineEdit,QComboBox {background:#fffef9;color:#263a30;selection-background-color:#cce3d4;
    selection-color:#183b27;border:1px solid #c3d2c5;border-radius:11px;padding:10px;}
QPushButton {background:#edf3e8;color:#294735;border:1px solid #bbceba;border-radius:9px;padding:8px 12px;min-height:22px;}
QPushButton:hover {background:#dfeadb;}
QPushButton:disabled {background:#edf0e9;color:#7d897d;border-color:#d7dfd2;}
QPushButton:focus,QComboBox:focus,QPlainTextEdit:focus,QLineEdit:focus {border:2px solid #326bb3;}
QScrollBar:vertical {background:transparent;width:7px;}
QScrollBar::handle:vertical {background:#bdcebd;border-radius:3px;min-height:24px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
QCheckBox {color:#263a30;spacing:8px;} QStatusBar {background:#e8eee3;color:#4b6550;}
QComboBox QAbstractItemView {background:#fffef9;color:#263a30;selection-background-color:#dcebdc;}
'''
