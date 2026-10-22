import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, 
    QHBoxLayout, QPushButton, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QPainter, QColor, QFont, QPen

class A11yWidget(QWidget):
    def __init__(self):
        super().__init__()

        # 1. Configurare fereastră nativă transparentă & Always-on-Top
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |       # Fără margini de fereastră
            Qt.WindowType.WindowStaysOnTopHint |     # Mereu peste orice aplicație
            Qt.WindowType.SubWindow                  # Nu încarcă taskbar-ul
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) # Fundal complet invizibil

        # 2. Datele scenariului de lucru (Misiunea pas-cu-pas)
        self.steps = [
            "Salut! Sunt A11y. Hai să luăm task-ul pas cu pas. Deschide fișierul Q3.",
            "Pasul 1: Filtrează coloana 'Status' și caută doar anomaliile.",
            "Pasul 2: Copiază rândurile cu erori într-un tabel separat.",
            "Pasul 3: Redactează un mesaj scurt către echipă: 'Raportul este gata'.",
            "Misiune îndeplinită! Ai terminat toate sarcinile fără stres! "
        ]
        self.current_step = 0

        # Stări grafice: 'idle' (verde), 'thinking' (galben), 'celebrate' (albastru)
        self.state = 'idle'
        self.pupil_offset = QPoint(0, 0)
        self.body_y_offset = 0

        # Variabilă pentru mutarea cu mouse-ul pe ecran
        self.drag_position = QPoint()

        # 3. Interfață grafică (Bula de dialog + Mascota)
        self.init_ui()

        # 4. Cronometru intern pentru micro-animații (ochi independenți & respirație)
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self.update_micro_animations)
        self.anim_timer.start(500)

        self.tick_count = 0

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Bula de dialog nativă
        self.bubble = QLabel(self.steps[self.current_step])
        self.bubble.setWordWrap(True)
        self.bubble.setFixedWidth(240)
        self.bubble.setStyleSheet("""
            background-color: #1e1e2e;
            color: #ffffff;
            border-radius: 12px;
            padding: 12px 14px;
            font-size: 13px;
            font-weight: 500;
            border: 2px solid #48bb78;
        """)

        # Umbră modernă pentru bulă
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 4)
        self.bubble.setGraphicsEffect(shadow)

        # Buton minimalist de acțiune pentru trecerea la următorul pas
        self.btn_next = QPushButton("Am făcut asta ➔")
        self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_next.setStyleSheet("""
            QPushButton {
                background-color: #48bb78;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: bold;
                margin-top: 6px;
            }
            QPushButton:hover {
                background-color: #38a169;
            }
        """)
        self.btn_next.clicked.connect(self.next_step)

        # Containerul de comenzi din bulă
        bubble_box = QVBoxLayout()
        bubble_box.addWidget(self.bubble)
        bubble_box.addWidget(self.btn_next, alignment=Qt.AlignmentFlag.AlignRight)

        layout.addLayout(bubble_box)
        layout.addSpacing(100) # Spațiu rezervat desenării cameleonului
        self.setLayout(layout)

        # Poziționare pe desktop (dreapta-jos a ecranului)
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen.width() - 320, screen.height() - 360, 280, 260)

    # --- DESENAREA VECTORIALĂ A CAMELEONULUI ---
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Centrul unde este desenat cameleonul
        cx = 140
        cy = 190 + self.body_y_offset

        # 1. Culori în funcție de starea curentă
        if self.state == 'idle':
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

    def next_step(self):
        if self.current_step < len(self.steps) - 1:
            self.current_step += 1
            
            # Trecere prin starea 'celebrate'
            self.state = 'celebrate'
            self.bubble.setStyleSheet(self.bubble.styleSheet().replace("#48bb78", "#4299e1"))
            self.bubble.setText(self.steps[self.current_step])
            self.update()

            # Revine la calm după 1.5 secunde
            QTimer.singleShot(1500, self.reset_to_idle)
        else:
            self.btn_next.setText("Restart misiune")
            self.current_step = -1

    def reset_to_idle(self):
        self.state = 'idle'
        self.bubble.setStyleSheet(self.bubble.styleSheet().replace("#4299e1", "#48bb78"))
        self.update()

    # --- CONTROL DE DRAG & DROP CU MOUSE-UL PE DESKTOP ---
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    widget = A11yWidget()
    widget.show()
    sys.exit(app.exec())