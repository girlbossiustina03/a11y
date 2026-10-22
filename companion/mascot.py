"""Interactive mascot conversation. Artwork is independently replaceable."""
import os
from PyQt6.QtWidgets import (
    QApplication, QWidget, QFrame, QVBoxLayout, QHBoxLayout, QPushButton,
    QPlainTextEdit, QLineEdit, QLabel, QAbstractButton, QMenu, QScrollArea, QGraphicsDropShadowEffect)
from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSignal, QRect
from PyQt6.QtGui import QPainter, QColor, QPen, QShortcut, QKeySequence, QPixmap, QFontMetrics


class Composer(QPlainTextEdit):
    returnPressed = pyqtSignal()

    def setText(self, value):
        self.setPlainText(value)

    def text(self):
        return self.toPlainText()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.returnPressed.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class Mascot(QWidget):
    opened = pyqtSignal()
    action_requested = pyqtSignal(str)
    submitted = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle('A11y · Desktop companion')
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAccessibleName('Desktop companion. Conversation and task controls.')
        self.setObjectName('mascotRoot')
        self.idle_footer = 'Enter to send · Shift+Enter for a new line'
        self.state = 'idle'
        self.submit_action = 'chat'
        self.drag_position = None
        self.busy = False
        self.user_collapsed = False
        self.expanded_width = 240
        self.card = QFrame()
        self.card.setObjectName('conversationCard')
        card_layout = QVBoxLayout(self.card)
        self.card_layout = card_layout
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(12)
        self.header_widget = QWidget()
        header = QHBoxLayout(self.header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel('A11y')
        title.setObjectName('companionTitle')
        header.addWidget(title)
        self.status = QLabel('Ready')
        self.status.setObjectName('activityLabel')
        self.status.setAccessibleName('Companion activity')
        header.addWidget(self.status, 1)
        settings = QPushButton('Settings')
        self.settings_button = settings
        settings.setObjectName('quietButton')
        settings.clicked.connect(self.opened)
        header.addWidget(settings)
        self.vision_button = QPushButton('Screen off')
        self.vision_button.setObjectName('quietButton')
        self.vision_button.setAccessibleName('Screen vision is off. Activate to enable local screen vision.')
        self.vision_button.clicked.connect(lambda: self.action_requested.emit('vision:toggle'))
        header.addWidget(self.vision_button)
        more = QPushButton('⋯')
        more.setObjectName('quietButton')
        more.setFixedWidth(28)
        more.setAccessibleName('Companion actions')
        more.clicked.connect(lambda: self.show_menu())
        header.addWidget(more)
        collapse = QPushButton('−')
        collapse.setObjectName('quietButton')
        collapse.setFixedWidth(30)
        collapse.setAccessibleName('Collapse conversation. Activate the character to reopen.')
        collapse.clicked.connect(self.toggle_chat)
        header.addWidget(collapse)
        card_layout.addWidget(self.header_widget)
        self.context_button = QPushButton('Desktop context off  ·  Enable')
        self.context_button.setObjectName('contextButton')
        self.context_button.clicked.connect(lambda: self.action_requested.emit('context:toggle'))
        card_layout.addWidget(self.context_button)
        self.bubble = QPlainTextEdit()
        self.bubble.setReadOnly(True)
        self.bubble.setAccessibleName('What your companion says')
        self.bubble.setFixedHeight(160)
        self.bubble.setFrameShape(QFrame.Shape.NoFrame)
        self.bubble.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        card_layout.addWidget(self.bubble)
        self.stage = QLabel('')
        self.stage.setObjectName('detailLabel')
        self.stage.setWordWrap(True)
        card_layout.addWidget(self.stage)
        self.choice_box = QWidget()
        self.choice_layout = QVBoxLayout(self.choice_box)
        self.choice_layout.setContentsMargins(0, 0, 0, 0)
        self.choice_layout.setSpacing(6)
        self.choice_area = QScrollArea()
        self.choice_area.setWidgetResizable(True)
        self.choice_area.setFrameShape(QFrame.Shape.NoFrame)
        self.choice_area.setWidget(self.choice_box)
        self.choice_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.choice_area.setFixedHeight(100)
        card_layout.addWidget(self.choice_area)
        self.entry_row = QWidget()
        entry = QHBoxLayout(self.entry_row)
        self.entry_layout = entry
        entry.setSpacing(8)
        entry.setContentsMargins(0, 0, 0, 0)
        self.input = Composer()
        self.input.setObjectName('composer')
        self.input.setFixedHeight(88)
        self.input.setFrameShape(QFrame.Shape.NoFrame)
        self.input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.input.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.input.document().setDocumentMargin(0)
        self.input.setTabChangesFocus(True)
        self.input.textChanged.connect(self.limit_input)
        self.input.setAccessibleName('Reply to your companion')
        self.input.returnPressed.connect(self.submit)
        self.send = QPushButton('↑')
        self.send.setAccessibleName('Send your message')
        self.send.setObjectName('sendButton')
        self.send.setFixedSize(42, 42)
        self.send.clicked.connect(self.submit)
        entry.addWidget(self.send, 0, Qt.AlignmentFlag.AlignVCenter)
        self.prompt_settings = QPushButton('⚙')
        self.prompt_settings.setObjectName('promptSettings')
        self.prompt_settings.setFixedSize(32, 32)
        self.prompt_settings.setAccessibleName('Open companion settings')
        self.prompt_settings.setToolTip('Settings · Right-click the character for more actions')
        self.prompt_settings.clicked.connect(self.opened)
        entry.addWidget(self.prompt_settings, 0, Qt.AlignmentFlag.AlignVCenter)
        entry.addWidget(self.input, 1, Qt.AlignmentFlag.AlignVCenter)
        card_layout.addWidget(self.entry_row)
        self.footer = QLabel(self.idle_footer)
        self.footer.setObjectName('detailLabel')
        self.footer.setWordWrap(True)
        card_layout.addWidget(self.footer)
        self.character = CharacterButton(self)
        self.character.clicked.connect(self.toggle_chat)
        self.character.setToolTip('Click to chat · Drag to move · Right-click for actions')
        self.character.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.character.customContextMenuRequested.connect(
            lambda point: self.show_menu(self.character.mapToGlobal(point)))
        self.character_row = QWidget()
        bottom = QHBoxLayout(self.character_row)
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.addStretch()
        bottom.addWidget(self.character)
        bottom.addStretch()
        self.controls_row = QWidget()
        self.controls_layout = QHBoxLayout(self.controls_row)
        self.controls_layout.setContentsMargins(0, 0, 0, 0)
        self.controls_layout.setSpacing(6)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        self.reply_panel = QFrame()
        self.reply_panel.setObjectName('replyPanel')
        self.reply_layout = QVBoxLayout(self.reply_panel)
        self.reply_layout.setContentsMargins(16, 12, 16, 12)
        self.reply_layout.setSpacing(8)
        self.reply_panel.hide()
        self.reply_available = False
        layout.addWidget(self.reply_panel)
        layout.addWidget(self.character_row)
        self.controls_layout.addWidget(self.card)
        layout.addWidget(self.controls_row)
        for surface in (self.card, self.reply_panel, self.send, self.prompt_settings):
            shadow = QGraphicsDropShadowEffect(surface)
            shadow.setBlurRadius(12)
            shadow.setOffset(0, 2)
            shadow.setColor(QColor(0, 0, 0, 26))
            surface.setGraphicsEffect(shadow)
        self.setFixedWidth(420)
        self.setStyleSheet("""
            QWidget#mascotRoot {background:transparent;color:#25352f;font-size:13px;}
            QFrame#conversationCard {background:#fffef9;border:1px solid #b7c7ba;border-radius:20px;}
            QFrame#conversationCard[promptOnly="true"] {background:#fafafa;border:1px solid #d6d6d9;border-radius:17px;}
            QFrame#replyPanel {background:#fafafa;border:1px solid #d6d6d9;border-radius:20px;}
            QFrame#replyPanel QPlainTextEdit {background:transparent;color:#242426;}
            QPlainTextEdit {background:#fffef9;color:#25352f;border:0;padding:0;font-size:14px;
                selection-background-color:#d0e7db;selection-color:#172f27;}
            QPlainTextEdit#composer {background:#f2f5ef;border:1px solid #c3d2c5;border-radius:12px;padding:10px;color:#233b30;font-size:14px;}
            QPlainTextEdit#composer:focus {border:2px solid #398267;padding:9px;}
            QLabel {color:#25352f;background:transparent;font-size:13px;}
            QLabel#companionTitle {font-size:18px;font-weight:700;}
            QLabel#activityLabel {color:#477962;font-size:11px;}
            QLabel#detailLabel {color:#627267;font-size:11px;}
            QPushButton {background:#f3f6ef;color:#2e493b;border:1px solid #cfdbce;border-radius:9px;
                padding:8px 12px;min-height:20px;font-size:12px;text-align:left;}
            QPushButton:hover {background:#e7efe3;border-color:#87a58c;}
            QPushButton:focus {border:2px solid #326bb3;}
            QPushButton:disabled {color:#78857c;background:#f0f2ed;}
            QPushButton#quietButton {background:transparent;border:0;font-size:11px;padding:4px;}
            QPushButton#contextButton {background:#edf3e8;border:0;border-radius:7px;color:#466347;font-size:11px;padding:7px 10px;}
            QPushButton#sendButton {background:#007aff;color:#ffffff;border:0;border-radius:16px;font-size:18px;text-align:center;padding:0;min-height:0;}
            QPushButton#promptSettings {background:#fafafa;color:#515155;border:1px solid #d6d6d9;border-radius:16px;
                font-size:16px;text-align:center;padding:0;min-height:0;}
            QPushButton#promptSettings:hover {background:#ededf0;}
            QPushButton#promptSettings[screenVision="true"] {background:#d4e9d9;border:2px solid #398267;}
            QPlainTextEdit#composer[promptOnly="true"] {background:transparent;border:0;border-radius:0;padding:0;font-size:12px;}
            QPlainTextEdit#composer[promptOnly="true"]:focus {border:0;padding:0;font-size:12px;}
            QPushButton#sendButton:hover {background:#0066d6;}
            QPushButton#sendButton:focus, QPushButton#promptSettings:focus {border:2px solid #72b4ff;}
            QScrollArea,QScrollArea > QWidget > QWidget {background:transparent;border:0;}
            QScrollBar:vertical {background:transparent;width:6px;margin:2px;}
            QScrollBar::handle:vertical {background:#b2c4b6;border-radius:3px;min-height:20px;}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
            QMenu {background:#fffef9;color:#25352f;border:1px solid #b7c7ba;padding:6px;}
            QMenu::item {padding:8px 16px;} QMenu::item:selected {background:#e7efe3;}
        """)
        self.resize(390, 560)
        self.place_on_screen()
        for key, delta in [('Left',(-20,0)), ('Right',(20,0)), ('Up',(0,-20)), ('Down',(0,20))]:
            shortcut = QShortcut(QKeySequence('Alt+'+key), self)
            shortcut.activated.connect(lambda d=delta: self.move(self.pos()+QPoint(*d)))
        QShortcut(QKeySequence('Escape'), self).activated.connect(self.collapse_chat)
        QShortcut(QKeySequence('Shift+F10'), self).activated.connect(lambda: self.show_menu())
        QShortcut(QKeySequence('Menu'), self).activated.connect(lambda: self.show_menu())

    def place_on_screen(self):
        area = self.screen().availableGeometry()
        self.move(max(area.left(), area.right()-self.width()-20),
                  max(area.top(), area.bottom()-self.sizeHint().height()-20))

    def fit_on_screen(self, character_anchor=None):
        # Qt can retain the expanded layout minimum after its card is hidden.
        self.setMinimumHeight(0)
        self.layout().invalidate()
        self.layout().activate()
        self.adjustSize()
        self.layout().activate()
        if character_anchor is not None:
            self.move(self.pos()+character_anchor-self.character.mapToGlobal(QPoint()))
        area = self.screen().availableGeometry()
        self.move(max(area.left(), min(self.x(), area.right()-self.width())),
                  max(area.top(), min(self.y(), area.bottom()-self.height())))

    def present(self, message, choices=(), *, placeholder=None, value='', submit_action='chat', stage='', compact=False):
        anchor = self.character.mapToGlobal(QPoint()) if self.isVisible() else None
        self.expanded_width = 240 if compact else 420
        self.header_widget.setVisible(not compact)
        self.card.setProperty('promptOnly', compact)
        self.input.setProperty('promptOnly', compact)
        # Apply directly so Qt also recalculates the text viewport after mode changes.
        self.input.setStyleSheet(
            'QPlainTextEdit {background:transparent;border:0;padding:0;font-size:12px;}'
            'QPlainTextEdit:focus {border:0;padding:0;}' if compact else '')
        for widget in (self.card, self.input):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.card_layout.setContentsMargins(12, 2, 12, 2) if compact else self.card_layout.setContentsMargins(18, 16, 18, 16)
        self.card_layout.setSpacing(0 if compact else 12)
        # The prompt is its own surface. Actions float beside it, below the character.
        for button in (self.send, self.prompt_settings):
            self.entry_layout.removeWidget(button)
            self.controls_layout.removeWidget(button)
        if compact:
            self.controls_layout.insertWidget(1, self.send, 0, Qt.AlignmentFlag.AlignVCenter)
            self.controls_layout.insertWidget(2, self.prompt_settings, 0, Qt.AlignmentFlag.AlignVCenter)
        else:
            self.entry_layout.insertWidget(0, self.send)
            self.entry_layout.insertWidget(1, self.prompt_settings)
        self.layout().removeWidget(self.character_row)
        self.layout().insertWidget(1 if compact else 2, self.character_row)
        self.send.setFixedSize(32, 32)
        self.prompt_settings.setFixedSize(32, 32)
        self.prompt_settings.setVisible(compact)
        # Replies have their own speech bubble; the prompt surface contains only input/actions.
        for widget in (self.bubble, self.choice_area):
            self.card_layout.removeWidget(widget)
            self.reply_layout.removeWidget(widget)
            if compact:
                self.reply_layout.addWidget(widget)
            else:
                self.card_layout.insertWidget(2 if widget is self.bubble else 4, widget)
        self.compact = compact
        self.settings_button.setVisible(not compact)
        self.context_button.setVisible(not compact)
        self.footer.setVisible(not compact)
        self.input.setFixedHeight(self.input.fontMetrics().height()+2 if compact else 88)
        self.card.setFixedHeight(34) if compact else self.card.setMaximumHeight(16777215)
        if not compact:
            self.card.setMinimumHeight(0)
        self.bubble.setVisible(bool(message))
        self.bubble.setPlainText(message)
        self.size_message(message)
        self.stage.setText(stage)
        self.stage.setVisible(bool(stage) and not compact)
        while self.choice_layout.count():
            item = self.choice_layout.takeAt(0)
            item.widget().hide()
            item.widget().deleteLater()
        for title, action in choices:
            choice = QPushButton(title)
            choice.setProperty('companion_action', action)
            choice.clicked.connect(lambda checked=False, a=action: self.action_requested.emit(a))
            self.choice_layout.addWidget(choice)
        self.choice_area.setFixedHeight(min(190, len(choices)*44))
        self.choice_area.setVisible(bool(choices))
        self.entry_row.setVisible(placeholder is not None)
        self.submit_action = submit_action
        self.input.setPlaceholderText(placeholder or '')
        self.input.setText(value)
        self.reply_available = bool(message) or bool(choices)
        self.reply_panel.setVisible(compact and self.reply_available and not self.user_collapsed)
        self.controls_row.setVisible(not self.user_collapsed)
        self.card.setVisible(not self.user_collapsed)
        self.setFixedWidth(self.expanded_width if not self.user_collapsed else self.character.width()+16)
        self.fit_on_screen(anchor)
        if placeholder is not None and self.card.isVisible() and self.isActiveWindow():
            self.input.setFocus()

    def size_message(self, message):
        metrics = QFontMetrics(self.bubble.font())
        rect = metrics.boundingRect(QRect(0, 0, self.expanded_width-56, 5000), Qt.TextFlag.TextWordWrap, message)
        self.bubble.setFixedHeight(max(42 if getattr(self, 'compact', False) else 68, min(170 if getattr(self, 'compact', False) else 220, rect.height()+16)))

    def limit_input(self):
        value = self.input.toPlainText()
        if len(value) > 6000:
            self.input.setPlainText(value[:6000])

    def submit(self, checked=False):
        if self.busy:
            return
        value = self.input.text().strip()
        if value:
            self.submitted.emit(value, self.submit_action)

    def set_busy(self, busy):
        self.busy = busy
        self.input.setEnabled(not busy)
        self.send.setEnabled(not busy)
        self.choice_box.setEnabled(not busy)
        self.footer.setText('Thinking locally…' if busy else self.idle_footer)

    def set_state(self, state, message=None):
        self.state = state
        self.character.state = state
        self.status.setText({'thinking':'Thinking…', 'speaking':'Speaking', 'guiding':'Next step',
                             'celebrate':'Saved', 'listening':'Listening'}.get(state, 'Ready'))
        if message:
            self.bubble.setPlainText(message)
            self.size_message(message)
        self.character.update()

    def set_reduced_motion(self, enabled):
        self.character.set_reduced_motion(enabled)

    def collapse_chat(self):
        anchor = self.character.mapToGlobal(QPoint())
        self.user_collapsed = True
        self.card.hide()
        self.controls_row.hide()
        self.reply_panel.hide()
        self.setFixedWidth(self.character.width()+16)
        self.fit_on_screen(anchor)
        self.character.setFocus()

    def expand_chat(self):
        anchor = self.character.mapToGlobal(QPoint())
        self.user_collapsed = False
        self.setFixedWidth(self.expanded_width)
        self.controls_row.show()
        self.card.show()
        self.reply_panel.hide()
        self.fit_on_screen(anchor)
        if self.entry_row.isVisible():
            self.input.setFocus()

    def toggle_chat(self):
        if self.user_collapsed or self.card.isHidden():
            self.expand_chat()
        else:
            self.collapse_chat()

    def set_screen_vision_indicator(self, enabled):
        if self.prompt_settings.property('screenVision') == enabled:
            return
        self.prompt_settings.setProperty('screenVision', enabled)
        self.prompt_settings.style().unpolish(self.prompt_settings)
        self.prompt_settings.style().polish(self.prompt_settings)
        self.prompt_settings.setFixedSize(32, 32)
        self.prompt_settings.setToolTip('Settings · Screen vision '+('on: each prompt includes a local screen image' if enabled else 'off'))

    def hide_reply(self):
        anchor = self.character.mapToGlobal(QPoint())
        self.reply_panel.hide()
        self.fit_on_screen(anchor)

    def show_reply(self):
        if self.reply_available:
            self.expand_chat()
            anchor = self.character.mapToGlobal(QPoint())
            self.reply_panel.show()
            self.fit_on_screen(anchor)

    def show_menu(self, position=None):
        menu = QMenu(self)
        menu.setAccessibleName('Companion actions')
        for title, action in [('Talk to me', 'talk'), ('Show last reply', 'reply'), ('Plan a task from my prompt', 'plan'), ('Mark current task step done', 'confirm'),
                              ('Pause screen vision' if self.vision_button.text() == 'Screen on' else 'Enable screen vision…', 'vision:toggle'), ('Move beside the suggested control', 'guide'), ('Sources and conversation', 'history'), ('My saved tasks', 'tasks'), ('Desktop context and controls', 'context:details'),
                              ('Get to know me again', 'setup:restart'), ('Read this aloud', 'read'),
                              ('Stop speech', 'stop_speech'), ('Settings and company documents', 'settings'), ('Quit companion', 'quit')]:
            item = menu.addAction(title)
            item.triggered.connect(lambda checked=False, a=action: self.action_requested.emit(a))
        menu.exec(position or self.character.mapToGlobal(self.character.rect().topLeft()))
        menu.deleteLater()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint()-self.pos()

    def mouseMoveEvent(self, event):
        if self.drag_position is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint()-self.drag_position)

    def mouseReleaseEvent(self, event):
        self.drag_position = None


class CharacterButton(QAbstractButton):
    """Replaceable visual. Optional A11Y_MASCOT_IMAGE supports supplied transparent PNG artwork."""
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.state = 'idle'
        self.pupil_offset = QPoint()
        self.body_y_offset = 0
        self.tick_count = 0
        self.press_position = None
        self.dragging = False
        self.setFixedSize(150, 110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName('Companion character. Activate to open or collapse chat; drag to move. Right-click or Shift+F10 for actions.')
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.artwork = QPixmap(os.getenv('A11Y_MASCOT_IMAGE', ''))
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self.update_micro_animations)
        self.anim_timer.start(500)

    def set_reduced_motion(self, enabled):
        if enabled:
            self.anim_timer.stop()
            self.body_y_offset = 0
            self.pupil_offset = QPoint()
            self.update()
        else:
            self.anim_timer.start(500)

    def mousePressEvent(self, event):
        self.press_position = event.globalPosition().toPoint()
        self.owner_position = self.owner.pos()
        self.dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.press_position is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint()-self.press_position
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self.dragging = True
            if self.dragging:
                self.owner.move(self.owner_position+delta)
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.dragging:
            self.setDown(False)
        else:
            super().mouseReleaseEvent(event)
        self.press_position = None
        self.dragging = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.artwork.isNull():
            image = self.artwork.scaled(140, 100, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap((self.width()-image.width())//2, (self.height()-image.height())//2+self.body_y_offset, image)
            return

        # Original placeholder until supplied candy-man artwork is available.
        cx = self.width() // 2
        cy = self.height() // 2 + self.body_y_offset

        # 1. Culori în funcție de starea curentă
        if self.state in ('idle', 'listening', 'speaking', 'guiding'):
            body_color = QColor("#48bb78")      # Verde calm
            headphone_color = QColor("#3182ce") # Căști albastre
        elif self.state == 'thinking':
            body_color = QColor("#ecc94b")      # Galben gânditor
            headphone_color = QColor("#dd6b20")
        elif self.state == 'celebrate':
            body_color = QColor("#4299e1")      # Albastru sărbătorire
            headphone_color = QColor("#9f7aea")

        # 2. Coadă spiralată de cameleon
        painter.setPen(QPen(body_color, 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(cx - 65, cy - 10, 40, 40, 0, 270 * 16)

        # 3. Picioare
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2f855a"))
        painter.drawRoundedRect(cx - 30, cy + 18, 14, 10, 4, 4)
        painter.drawRoundedRect(cx + 10, cy + 18, 14, 10, 4, 4)

        # 4. Corp principal
        painter.setBrush(body_color)
        painter.drawRoundedRect(cx - 40, cy - 25, 75, 45, 18, 18)

        # 5. Căști Audio Mari (Simbol pentru suport senzorial / A11y)
        painter.setPen(QPen(QColor("#2d3748"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(cx - 30, cy - 42, 55, 45, 0, 180 * 16) # Banda de sus
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(headphone_color)
        painter.drawRoundedRect(cx - 36, cy - 30, 10, 22, 4, 4)  # Cupa stângă
        painter.drawRoundedRect(cx + 20, cy - 30, 10, 22, 4, 4)  # Cupa dreaptă

        # 6. Ochii specifici de cameleon (mari și independenți)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(cx - 16, cy - 20, 20, 20) # Ochi stâng
        painter.drawEllipse(cx + 4, cy - 20, 18, 18)  # Ochi drept

        # Pupile mobile
        painter.setBrush(QColor("#1a202c"))
        painter.drawEllipse(cx - 8 + self.pupil_offset.x(), cy - 12 + self.pupil_offset.y(), 6, 6)
        painter.drawEllipse(cx + 10 - self.pupil_offset.x(), cy - 12 + self.pupil_offset.y(), 5, 5)

        # 7. Zâmbet prietenos
        painter.setPen(QPen(QColor("#1a202c"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(cx + 10, cy + 2, 14, 10, 200 * 16, 120 * 16)

    # --- ANIMAȚIILE ȘI COMPORTAMENTUL ---
    def update_micro_animations(self):
        self.tick_count += 1

        # Mișcare lentă a corpului (respirație)
        self.body_y_offset = -2 if (self.tick_count % 2 == 0) else 0

        # Mișcare independentă a ochilor
        positions = [QPoint(0, 0), QPoint(-2, -1), QPoint(2, 1), QPoint(-1, 2)]
        self.pupil_offset = positions[self.tick_count % len(positions)]

        self.update() # Forțează re-desenarea

