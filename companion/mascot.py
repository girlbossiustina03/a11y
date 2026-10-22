"""Interactive mascot conversation. Artwork is independently replaceable."""
import math
import os
from .theme import MASCOT_STYLE
from .icons import control_icon
from PyQt6.QtWidgets import (
    QApplication, QWidget, QFrame, QVBoxLayout, QHBoxLayout, QPushButton,
    QPlainTextEdit, QLineEdit, QLabel, QAbstractButton, QMenu, QScrollArea, QGraphicsDropShadowEffect)
from PyQt6.QtCore import Qt, QTimer, QPoint, QPointF, QRectF, QElapsedTimer, pyqtSignal, QRect, QSize, QEvent
from PyQt6.QtGui import QPainter, QPainterPath, QColor, QPen, QShortcut, QKeySequence, QPixmap, QFontMetrics


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
        self.input.installEventFilter(self)
        self.input.returnPressed.connect(self.submit)
        self.send = QPushButton()
        self.send.setIcon(control_icon('send'))
        self.send.setIconSize(QSize(20, 20))
        self.send.setToolTip('Send message · Enter')
        self.send.setAccessibleName('Send your message')
        self.send.setObjectName('sendButton')
        self.send.setFixedSize(42, 42)
        self.send.clicked.connect(self.submit)
        entry.addWidget(self.send, 0, Qt.AlignmentFlag.AlignVCenter)
        self.prompt_settings = QPushButton()
        self.prompt_settings.setIcon(control_icon('settings'))
        self.prompt_settings.setIconSize(QSize(20, 20))
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
            shadow.setColor(QColor(0, 0, 0, 85))
            surface.setGraphicsEffect(shadow)
        self.setFixedWidth(420)
        self.setStyleSheet(MASCOT_STYLE)
        self.resize(390, 560)
        self.place_on_screen()
        for key, delta in [('Left',(-20,0)), ('Right',(20,0)), ('Up',(0,-20)), ('Down',(0,20))]:
            shortcut = QShortcut(QKeySequence('Alt+'+key), self)
            shortcut.activated.connect(lambda d=delta: self.move(self.pos()+QPoint(*d)))
        QShortcut(QKeySequence('Escape'), self).activated.connect(self.collapse_chat)
        QShortcut(QKeySequence('Shift+F10'), self).activated.connect(lambda: self.show_menu())
        QShortcut(QKeySequence('Menu'), self).activated.connect(lambda: self.show_menu())

    def eventFilter(self, watched, event):
        if watched is self.input and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.card.setProperty('inputFocused', event.type() == QEvent.Type.FocusIn)
            self.card.style().unpolish(self.card)
            self.card.style().polish(self.card)
            self.card.update()
        return super().eventFilter(watched, event)

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
        self.card.setProperty('inputFocused', False)
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
        for title, action in [('Talk to me', 'talk'), ('Show last reply', 'reply'),
                              ('My saved tasks', 'tasks'), ('Mark current step done', 'confirm'),
                              ('Pause screen vision' if self.vision_button.text() == 'Screen on' else 'Enable screen vision…', 'vision:toggle'),
                              ('Personalize and set up access…', 'setup:wizard'),
                              ('Settings…', 'settings'), ('Quit companion', 'quit')]:
            if action in ('vision:toggle', 'settings', 'quit'):
                menu.addSeparator()
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


# Paleta norișorului (din designul "Cloud Desktop Assistant")
CLOUD_SHADE = QColor('#E2EAF4')
CLOUD_BODY = QColor('#FFFFFF')
CLOUD_LINE = QColor('#C9D6E6')
CLOUD_INK = QColor('#1E2838')


def cloud_path():
    """Conturul norișorului, în coordonatele viewBox-ului original (-20 -20 240 180)."""
    path = QPainterPath(QPointF(57, 124))
    path.cubicTo(35, 124, 23, 108, 26, 90)
    path.cubicTo(29, 76, 41, 68, 53, 70)
    path.cubicTo(55, 46, 73, 30, 95, 32)
    path.cubicTo(111, 33, 123, 44, 129, 58)
    path.cubicTo(136, 50, 150, 50, 159, 60)
    path.cubicTo(168, 70, 168, 84, 163, 92)
    path.cubicTo(176, 96, 181, 110, 174, 120)
    path.cubicTo(170, 124, 165, 124, 159, 124)
    path.quadTo(108, 131, 57, 124)
    path.closeSubpath()
    return path


def ease_in_out(t):
    return 0.5 - 0.5 * math.cos(math.pi * t)


class CharacterButton(QAbstractButton):
    """Replaceable visual. Optional A11Y_MASCOT_IMAGE supports supplied transparent PNG artwork.

    Default artwork: the A11y cloud, idle state only (slow float + blink)."""
    SCALE = 0.75            # din coordonatele designului în cele ale butonului 150x110
    FLOAT_PERIOD = 4000     # ms, plutire sus-jos
    FLOAT_HEIGHT = 8        # px, în coordonatele designului
    BLINK_PERIOD = 4200     # ms, un clipit pe ciclu

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.state = 'idle'
        self.press_position = None
        self.dragging = False
        self.reduced_motion = False
        self.setFixedSize(150, 110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName('Companion character. Activate to open or collapse chat; drag to move. Right-click or Shift+F10 for actions.')
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.artwork = QPixmap(os.getenv('A11Y_MASCOT_IMAGE', ''))
        self.cloud = cloud_path()
        self.clock = QElapsedTimer()
        self.clock.start()
        # ~30 fps pentru plutire și clipit fluide
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self.update)
        self.anim_timer.start(33)

    def set_reduced_motion(self, enabled):
        self.reduced_motion = enabled
        if enabled:
            self.anim_timer.stop()
        else:
            self.anim_timer.start(33)
        self.update()

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

    def float_phase(self):
        """0 -> 1 -> 0 pe parcursul unui ciclu de plutire."""
        if self.reduced_motion:
            return 0.0
        t = (self.clock.elapsed() % self.FLOAT_PERIOD) / self.FLOAT_PERIOD
        return ease_in_out(t * 2) if t < 0.5 else ease_in_out((1 - t) * 2)

    def blink_scale(self):
        """Scala verticală a ochilor: 1 normal, 0.1 la mijlocul clipitului."""
        if self.reduced_motion:
            return 1.0
        t = (self.clock.elapsed() % self.BLINK_PERIOD) / self.BLINK_PERIOD
        if 0.90 <= t < 0.94:
            return 1 - 0.9 * (t - 0.90) / 0.04
        if 0.94 <= t < 1.0:
            return 0.1 + 0.9 * (t - 0.94) / 0.06
        return 1.0

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        phase = self.float_phase()
        lift = self.FLOAT_HEIGHT * self.SCALE * phase

        if not self.artwork.isNull():
            image = self.artwork.scaled(140, 100, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap((self.width()-image.width())//2, int((self.height()-image.height())//2-lift), image)
            return

        # Norul e centrat pe orizontală (mijlocul lui e la x=102 în design)
        painter.translate(self.width()/2 - 102*self.SCALE, 14 - 32*self.SCALE)
        painter.scale(self.SCALE, self.SCALE)

        # 1. Umbra de sub nor (se strânge când norul urcă)
        shadow_w = 110 * (1 - 0.18*phase)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, int(255*0.28*(1 - 0.4*phase))))
        painter.drawEllipse(QRectF(100 - shadow_w/2, 138, shadow_w, 12))

        # 2. Corpul norului: umbră internă, corp alb, contur
        painter.translate(0, -self.FLOAT_HEIGHT*phase)
        painter.setBrush(CLOUD_SHADE)
        painter.drawPath(self.cloud)
        painter.save()
        painter.translate(23, 0)
        painter.scale(0.95, 1)
        painter.translate(-23, 0)
        painter.setBrush(CLOUD_BODY)
        painter.drawPath(self.cloud)
        painter.restore()
        painter.setPen(QPen(CLOUD_LINE, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.cloud)

        # 3. Ochii deschiși, cu clipit
        blink = self.blink_scale()
        painter.setPen(Qt.PenStyle.NoPen)
        for cx in (82, 118):
            painter.save()
            painter.translate(cx, 87)
            painter.scale(1, blink)
            painter.setBrush(CLOUD_INK)
            painter.drawEllipse(QPointF(0, 0), 8, 10.5)
            painter.setBrush(CLOUD_BODY)
            painter.drawEllipse(QPointF(3, -4), 2.8, 2.8)
            painter.restore()

        # 4. Zâmbet
        smile = QPainterPath(QPointF(93, 104))
        smile.quadTo(100, 110, 107, 104)
        painter.setPen(QPen(CLOUD_INK, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(smile)

