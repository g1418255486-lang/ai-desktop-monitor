"""统一设置弹窗：额度监控 + 状态监控（opencode / DSH）两组配置。"""

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QFrame, QLineEdit, QComboBox, QSpinBox, QCheckBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from config import (
    load_config, save_config, PLATFORMS_CFG,
    DEFAULT_LOG_DIR, DEFAULT_DSH_DIR,
)
from app.frameless import SolidFramelessDialog
from app.theme import (
    PRIMARY, TEXT_HEADING, TEXT_BODY, TEXT_SECONDARY,
    BG, BG_CARD, BORDER_WARM, BORDER_STRONG, ERROR,
    qss_font,
    mono_font as _mono_font,
)


_INPUT_CSS = f"""
QLineEdit, QComboBox, QSpinBox {{
    background: {BG_CARD};
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    padding: 7px 11px;
    color: {TEXT_BODY};
    {qss_font(12, 500)}
    selection-background-color: rgba(0, 230, 118, 0.25);
    selection-color: {TEXT_HEADING};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{
    border-color: {TEXT_SECONDARY};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border-color: {PRIMARY};
    color: {TEXT_HEADING};
}}
QLineEdit::placeholder {{
    color: {TEXT_SECONDARY};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {BG};
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    padding: 4px;
    color: {TEXT_BODY};
    selection-background-color: {BG_CARD};
    selection-color: {PRIMARY};
    outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background: transparent; border: none; width: 16px;
}}
QSpinBox::up-arrow {{
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-bottom: 5px solid {TEXT_SECONDARY};
}}
QSpinBox::down-arrow {{
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_SECONDARY};
}}
QCheckBox {{
    {qss_font(12, 500)}
    color: {TEXT_BODY};
    spacing: 8px;
    padding: 2px 0;
}}
QCheckBox:hover {{ color: {TEXT_HEADING}; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {BORDER_STRONG};
    border-radius: 3px;
    background: {BG_CARD};
}}
QCheckBox::indicator:hover {{
    border-color: {TEXT_SECONDARY};
}}
QCheckBox::indicator:checked {{
    background: {PRIMARY};
    border-color: {PRIMARY};
}}
"""


class SettingsDialog(SolidFramelessDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(308)
        self.setMaximumWidth(308)

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        self._title_bar(root)
        self._hline(root)

        body = QVBoxLayout()
        body.setContentsMargins(24, 16, 24, 12)
        body.setSpacing(6)

        # ─── 额度监控 ───
        body.addWidget(self._section("QUOTA · 额度监控"))

        body.addWidget(self._label("API KEY"))
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setPlaceholderText("输入 API Key（留空则仅监控状态）")
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setStyleSheet(_INPUT_CSS)
        self.api_key_edit.setFont(_mono_font(12))
        body.addWidget(self.api_key_edit)

        body.addSpacing(6)
        body.addWidget(self._label("PLATFORM"))
        self.platform_combo = QComboBox()
        for key, info in PLATFORMS_CFG.items():
            self.platform_combo.addItem(info["name"], key)
        self.platform_combo.setStyleSheet(_INPUT_CSS)
        body.addWidget(self.platform_combo)

        body.addSpacing(6)
        body.addWidget(self._label("REFRESH"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(60, 3600)
        self.interval_spin.setSuffix(" 秒")
        self.interval_spin.setStyleSheet(_INPUT_CSS)
        body.addWidget(self.interval_spin)

        body.addSpacing(14)

        # ─── 状态监控 ───
        body.addWidget(self._section("STATUS · opencode / DSH 状态"))

        body.addWidget(self._label("OPENCODE LOG DIR"))
        self.logdir_edit = QLineEdit()
        self.logdir_edit.setPlaceholderText(f"留空自动检测 {DEFAULT_LOG_DIR}")
        self.logdir_edit.setStyleSheet(_INPUT_CSS)
        self.logdir_edit.setFont(_mono_font(11))
        body.addWidget(self.logdir_edit)

        body.addSpacing(6)
        body.addWidget(self._label("DSH SESSIONS DIR"))
        self.dshdir_edit = QLineEdit()
        self.dshdir_edit.setPlaceholderText(f"留空自动检测 {DEFAULT_DSH_DIR}")
        self.dshdir_edit.setStyleSheet(_INPUT_CSS)
        self.dshdir_edit.setFont(_mono_font(11))
        body.addWidget(self.dshdir_edit)

        body.addSpacing(8)
        self.notify_check = QCheckBox("需要关注时气泡提醒")
        self.notify_check.setStyleSheet(_INPUT_CSS)
        body.addWidget(self.notify_check)

        body.addSpacing(8)
        self.hud_check = QCheckBox("显示悬浮状态面板（HUD）")
        self.hud_check.setStyleSheet(_INPUT_CSS)
        body.addWidget(self.hud_check)

        body.addSpacing(6)
        body.addWidget(self._label("HUD SLOTS"))
        self.slots_spin = QSpinBox()
        self.slots_spin.setRange(1, 6)
        self.slots_spin.setSuffix(" 个")
        self.slots_spin.setStyleSheet(_INPUT_CSS)
        body.addWidget(self.slots_spin)

        root.addLayout(body)

        self._hline(root)

        btns = QHBoxLayout()
        btns.setContentsMargins(24, 10, 24, 18)
        btns.setSpacing(10)
        btns.addStretch()

        cancel = QPushButton("取消")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(
            f"QPushButton{{background:transparent;color:{TEXT_BODY};"
            f"border:1px solid {BORDER_STRONG};"
            f"border-radius:4px;padding:7px 18px;{qss_font(12, 600)}}}"
            f"QPushButton:hover{{border-color:{TEXT_SECONDARY};color:{TEXT_HEADING};}}"
        )
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)

        save = QPushButton("保存")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.setStyleSheet(
            f"QPushButton{{background:{PRIMARY};color:#062015;border:none;"
            f"border-radius:4px;padding:7px 22px;{qss_font(12, 700)}}}"
            "QPushButton:hover{background:#2dff92;}"
            "QPushButton:pressed{background:#00c853;}"
        )
        save.clicked.connect(self._accept)
        btns.addWidget(save)

        root.addLayout(btns)
        self._load()

    def _title_bar(self, layout):
        bar = QHBoxLayout()
        bar.setContentsMargins(18, 12, 8, 10)

        ind = QFrame()
        ind.setFixedSize(8, 8)
        ind.setStyleSheet(f"background:{PRIMARY};border:none;")
        bar.addWidget(ind)
        bar.addSpacing(9)

        t = QLabel("SETTINGS")
        t.setFont(_mono_font(12, QFont.Weight.Bold, 110))
        t.setStyleSheet(f"color:{TEXT_HEADING};background:transparent;")
        bar.addWidget(t)
        bar.addStretch()

        x = QPushButton("×")
        x.setFixedSize(26, 26)
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:4px;"
            f"font-size:16px;color:{TEXT_SECONDARY};}}"
            f"QPushButton:hover{{background:{BG_CARD};color:{ERROR};}}"
        )
        x.clicked.connect(self.reject)
        bar.addWidget(x)
        layout.addLayout(bar)

    @staticmethod
    def _section(text):
        s = QLabel(text)
        s.setFont(_mono_font(9, QFont.Weight.Bold, 160))
        s.setStyleSheet(f"color:{PRIMARY};background:transparent;")
        return s

    @staticmethod
    def _label(text):
        l = QLabel(text)
        l.setFont(_mono_font(9, QFont.Weight.Bold, 160))
        l.setStyleSheet(f"color:{TEXT_SECONDARY};background:transparent;")
        return l

    @staticmethod
    def _hline(layout):
        s = QFrame()
        s.setFixedHeight(1)
        s.setStyleSheet(f"background:{BORDER_WARM};border:none;")
        layout.addWidget(s)

    def _load(self):
        cfg = load_config()
        self.api_key_edit.setText(cfg.get("api_key", ""))
        platform = cfg.get("platform", "zhipu")
        idx = self.platform_combo.findData(platform)
        if idx >= 0:
            self.platform_combo.setCurrentIndex(idx)
        self.interval_spin.setValue(cfg.get("refresh_interval", 300))
        self.logdir_edit.setText(cfg.get("opencode_log_dir", ""))
        self.dshdir_edit.setText(cfg.get("dsh_sessions_dir", ""))
        self.notify_check.setChecked(bool(cfg.get("notify_on_attention", True)))
        self.hud_check.setChecked(bool(cfg.get("show_hud", True)))
        self.slots_spin.setValue(int(cfg.get("hud_slots", 3)))

    def _accept(self):
        key = self.api_key_edit.text().strip()
        if key and ("\n" in key or "\r" in key or " " in key or len(key) > 128):
            QMessageBox.warning(self, "提示", "API Key 格式不正确，请检查")
            return
        if not key:
            ret = QMessageBox.question(
                self, "提示", "未填写 API Key，将仅监控状态。继续保存？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return
        cfg = load_config()          # 基于现有配置更新，避免丢弃未知键
        cfg.update({
            "api_key": key,
            "platform": self.platform_combo.currentData(),
            "refresh_interval": self.interval_spin.value(),
            "opencode_log_dir": self.logdir_edit.text().strip(),
            "dsh_sessions_dir": self.dshdir_edit.text().strip(),
            "notify_on_attention": self.notify_check.isChecked(),
            "show_hud": self.hud_check.isChecked(),
            "hud_slots": self.slots_spin.value(),
        })
        if not save_config(cfg):
            QMessageBox.warning(self, "提示", "配置保存失败，请检查磁盘空间或权限")
            return
        self.accept()
