"""Small accessible settings surfaces with optional technical details."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QScrollArea, QToolButton, QVBoxLayout, QWidget


class Disclosure(QWidget):
    def __init__(self, title, *, expanded=False):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setAccessibleName(title)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setCheckable(True)
        self.toggle.setSizePolicy(self.sizePolicy().horizontalPolicy(), self.toggle.sizePolicy().verticalPolicy())
        self.toggle.setStyleSheet('QToolButton {color:#c7c7cf;background:transparent;border:1px solid transparent;'
                                 'border-radius:7px;padding:7px;text-align:left;}'
                                 'QToolButton:hover {background:#303034;}'
                                 'QToolButton:focus {border-color:#8bc2ff;}')
        layout.addWidget(self.toggle)
        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(8, 0, 0, 0)
        self.body.setSpacing(10)
        layout.addWidget(self.content)
        self.toggle.toggled.connect(self.set_expanded)
        self.toggle.setChecked(expanded)
        self.set_expanded(expanded)

    def set_expanded(self, expanded):
        self.content.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.toggle.setAccessibleDescription('Expanded' if expanded else 'Collapsed')


def scroll_page(page):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(page)
    return scroll
