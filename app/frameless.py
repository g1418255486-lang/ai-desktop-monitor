"""Frameless solid-background dialog base with rounded corners."""

from PySide6.QtWidgets import QDialog, QPushButton, QLineEdit, QComboBox, QSpinBox, QCheckBox
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath, QRegion
from PySide6.QtCore import Qt, QRectF

from app.theme import RADIUS, BG, BORDER_STRONG

class SolidFramelessDialog(QDialog):
    """Frameless dialog: translucent window attr + rounded mask + solid dark paint."""

    _INTERACTIVE = (QPushButton, QLineEdit, QComboBox, QSpinBox, QCheckBox)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Dialog
            | Qt.WindowType.WindowSystemMenuHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._drag_pos = None

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_rounded_mask()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_rounded_mask()

    def _apply_rounded_mask(self):
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()), RADIUS, RADIUS)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), RADIUS, RADIUS)
        p.fillPath(path, QColor(BG))
        p.setPen(QPen(QColor(BORDER_STRONG), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            w = self.childAt(event.position().toPoint())
            if not isinstance(w, self._INTERACTIVE):
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)
