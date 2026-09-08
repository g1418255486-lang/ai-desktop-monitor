"""托盘应用主控制器。

- 托盘图标：纯额度仪表盘（环形弧 + 5h 百分比数字），不编码 agent 状态
- 悬浮面板（StatusHud）：常驻置顶，状态逐会话槽位 + 可折叠额度区，
  状态与额度的唯一展示面
- 数据侧：QuotaWorker（QThread）与 WatcherWorker（QThread）互不阻塞
"""

import traceback

from PySide6.QtWidgets import QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QAction, QFont
from PySide6.QtCore import QTimer, QThread, Qt, QRectF, QPointF, QObject, Slot

from config import load_config, save_config, resolve_log_dir, resolve_dsh_dir
from services.quota_service import QuotaWorker, UsageData
from services.agent_watcher import (
    WatcherWorker, STATE_NEEDS_ATTENTION, STATE_DISCONNECTED,
)
from app.status_hud import StatusHud
from app.theme import (
    PRIMARY, TEXT_HEADING, BG, BORDER_STRONG,
    STATE_LABELS, menu_qss,
    mono_font as _mono_font,
    bar_color as _theme_bar_color,
)
from app.settings_dialog import SettingsDialog


def _bar_color(pct: float) -> QColor:
    return _theme_bar_color(pct)


def _create_icon(percentage: float = None) -> QIcon:
    # 4x supersampled rendering for crisp edges
    scale = 4
    size = 32
    big = size * scale
    cx, cy = big / 2, big / 2

    pixmap = QPixmap(big, big)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    r = big / 2 - 3 * scale
    ring_r = r - 3.5 * scale

    if percentage is not None:
        pct = max(0.0, min(100.0, float(percentage)))
        color = _bar_color(pct)

        # dark instrument disc
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(BG))
        painter.drawEllipse(QPointF(cx, cy), r, r)

        # rim so the disc reads on dark taskbars
        rim = QPen(QColor(BORDER_STRONG), 1.2 * scale)
        painter.setPen(rim)
        painter.drawEllipse(QPointF(cx, cy), r, r)

        # track + status arc (gauge)
        arc_rect = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
        track = QPen(QColor(31, 43, 38), 3 * scale)
        track.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(track)
        painter.drawArc(arc_rect, 0, 5760)

        span = int(pct / 100 * 5760)
        pen = QPen(color, 3 * scale)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        painter.drawArc(arc_rect, 1440, -span)

        # mono number
        painter.setFont(_mono_font(int(big * 0.34), QFont.Weight.Bold))
        painter.setPen(QColor(TEXT_HEADING))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, str(int(round(pct))))
    else:
        # idle "A" icon
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(BG))
        painter.drawEllipse(QPointF(cx, cy), r, r)

        rim = QPen(QColor(BORDER_STRONG), 1.2 * scale)
        painter.setPen(rim)
        painter.drawEllipse(QPointF(cx, cy), r, r)

        arc_rect = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
        pen = QPen(QColor(PRIMARY), 3 * scale)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        painter.drawArc(arc_rect, 1440, -int(0.62 * 5760))

        painter.setFont(_mono_font(int(big * 0.46), QFont.Weight.Bold))
        painter.setPen(QColor(PRIMARY))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "A")

    painter.end()

    out = pixmap.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return QIcon(out)


class TrayApp(QObject):
    """必须是 QObject：worker 线程的信号连接到本类的方法时，
    Qt 会按接收者（主线程）排队派发；否则回调在 worker 线程执行，
    跨线程操作 QAction/QWidget 会触发 setParent 线程错误。"""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.config = load_config()

        # 数据
        self.current_quota: UsageData = None
        self.current_status: dict = None
        self._last_state = STATE_DISCONNECTED
        self._no_key_notified = False

        # 线程引用
        self._quota_thread = None
        self._quota_worker = None
        self._watcher_thread = None
        self._watcher_worker = None

        # ─── 托盘 ───
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(_create_icon())
        self.tray.setToolTip("AI 桌面监控")
        self.tray.activated.connect(self._on_activated)

        menu = QMenu()
        menu.setStyleSheet(menu_qss())

        self.status_action = QAction("● 未连接", self.app)
        self.status_action.setEnabled(False)
        menu.addAction(self.status_action)

        menu.addSeparator()

        self.refresh_action = QAction("刷新余量", self.app)
        self.refresh_action.triggered.connect(self.refresh)
        menu.addAction(self.refresh_action)

        detail_action = QAction("查看额度", self.app)
        detail_action.triggered.connect(self.show_quota)
        menu.addAction(detail_action)

        menu.addSeparator()

        self.hud_action = QAction("显示状态面板", self.app)
        self.hud_action.setCheckable(True)
        self.hud_action.triggered.connect(lambda checked: self.set_hud_visible(checked))
        menu.addAction(self.hud_action)

        menu.addSeparator()

        settings_action = QAction("设置", self.app)
        settings_action.triggered.connect(self.show_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        quit_action = QAction("退出", self.app)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.show()

        # ─── 悬浮状态面板 ───
        self.hud = StatusHud(self)
        self._apply_hud()

        # ─── 额度定时器 ───
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh)
        self._start_timer()

        # ─── opencode 状态监控 ───
        self._start_watcher()

        # ─── 启动动作 ───
        if not self.config.get("api_key"):
            QTimer.singleShot(500, self.show_settings)
        else:
            QTimer.singleShot(1000, self.refresh)

    # ─── 额度轮询 ───

    def _start_timer(self):
        interval = self.config.get("refresh_interval", 300) * 1000
        self.timer.start(interval)

    def refresh(self):
        api_key = self.config.get("api_key", "")
        if not api_key:
            if not self._no_key_notified:
                self._no_key_notified = True
                self.tray.setToolTip("AI 桌面监控 - 未配置 API Key")
            return

        self._no_key_notified = False

        try:
            if self._quota_thread and self._quota_thread.isRunning():
                return
        except RuntimeError:
            self._quota_thread = None
            self._quota_worker = None

        self.refresh_action.setEnabled(False)
        self.tray.setToolTip("AI 桌面监控 - 正在刷新...")

        self._quota_thread = QThread()
        self._quota_worker = QuotaWorker(api_key, self.config.get("platform", "zhipu"))
        self._quota_worker.moveToThread(self._quota_thread)
        self._quota_worker.finished.connect(self._on_quota)
        self._quota_worker.finished.connect(self._quota_thread.quit)
        self._quota_thread.finished.connect(self._quota_worker.deleteLater)
        self._quota_thread.finished.connect(self._quota_thread.deleteLater)
        self._quota_thread.started.connect(self._quota_worker.run)
        self._quota_thread.start()

    @Slot(object)
    def _on_quota(self, data: UsageData):
        self.current_quota = data
        self.refresh_action.setEnabled(True)

        try:
            self.hud.update_quota(data)

            if data.error and data.token_5h_pct is None and data.token_weekly_pct is None:
                self.tray.setIcon(_create_icon())
                self.tray.setToolTip(f"AI 桌面监控 - 错误: {data.error[:50]}")
                self.tray.showMessage(
                    "查询失败", data.error[:100],
                    QSystemTrayIcon.MessageIcon.Critical, 5000,
                )
            else:
                parts = []
                if data.token_5h_pct is not None:
                    parts.append(f"Token(5h): {data.token_5h_pct:.0f}%")
                if data.token_weekly_pct is not None:
                    parts.append(f"Token(周): {data.token_weekly_pct:.0f}%")
                # 图标只编码 5h 窗口百分比
                icon_pct = data.token_5h_pct if data.token_5h_pct is not None else 0
                self.tray.setIcon(_create_icon(icon_pct))
                self.app.setWindowIcon(_create_icon(icon_pct))
                tip = "AI 桌面监控\n" + "\n".join(parts) if parts else "AI 桌面监控 - 无数据"
                self.tray.setToolTip(tip)
        except Exception:
            traceback.print_exc()

    # ─── agent 状态监控（opencode + DSH） ───

    def _start_watcher(self):
        self._stop_watcher()
        self._watcher_thread = QThread()
        self._watcher_worker = WatcherWorker(
            resolve_log_dir(self.config), resolve_dsh_dir(self.config)
        )
        self._watcher_worker.moveToThread(self._watcher_thread)
        self._watcher_worker.state_changed.connect(self._on_status)
        self._watcher_worker.finished.connect(self._watcher_thread.quit)
        self._watcher_thread.finished.connect(self._watcher_worker.deleteLater)
        self._watcher_thread.finished.connect(self._watcher_thread.deleteLater)
        self._watcher_thread.started.connect(self._watcher_worker.run)
        self._watcher_thread.start()

    def _stop_watcher(self):
        try:
            if self._watcher_worker:
                self._watcher_worker.stop()
        except RuntimeError:
            pass
        try:
            if self._watcher_thread and self._watcher_thread.isRunning():
                self._watcher_thread.quit()
                self._watcher_thread.wait(2500)
        except RuntimeError:
            pass
        self._watcher_worker = None
        self._watcher_thread = None

    @Slot(object)
    def _on_status(self, payload: dict):
        self.current_status = payload
        state = payload.get("state", STATE_DISCONNECTED)

        try:
            self.hud.update_payload(payload)

            label = STATE_LABELS.get(state, "未连接")
            active = payload.get("active", 0)
            text = f"● {label}"
            if state != STATE_DISCONNECTED and active:
                text += f" · {active} 会话"
            self.status_action.setText(text)

            if (state == STATE_NEEDS_ATTENTION
                    and self._last_state != STATE_NEEDS_ATTENTION
                    and self.config.get("notify_on_attention", True)):
                sources = payload.get("sources") or {}
                names = []
                for key, display in (("opencode", "opencode"), ("dsh", "DeepSeek Harness")):
                    src = sources.get(key) or {}
                    if src.get("state") == STATE_NEEDS_ATTENTION:
                        names.append(display)
                who = " / ".join(names) if names else "Agent"
                self.tray.showMessage(
                    f"{who} 需要关注", "会话正在提问或等待权限授权",
                    QSystemTrayIcon.MessageIcon.Warning, 4000,
                )
            self._last_state = state
        except Exception:
            traceback.print_exc()

        # 状态变化不再刷新弹窗（弹窗只管额度，状态统一看 HUD）

    # ─── 悬浮状态面板控制（供 StatusHud 回调） ───

    def set_hud_visible(self, visible: bool):
        self.config["show_hud"] = bool(visible)
        save_config(self.config)
        self.hud_action.setChecked(bool(visible))
        self.hud.setVisible(bool(visible))

    def set_hud_slots(self, n: int):
        self.config["hud_slots"] = int(n)
        save_config(self.config)
        self.hud.set_slots(int(n))

    def _apply_hud(self):
        self.hud.set_slots(int(self.config.get("hud_slots", 3)))
        visible = bool(self.config.get("show_hud", True))
        self.hud_action.setChecked(visible)
        self.hud.setVisible(visible)

    # ─── 额度查看（HUD 内折叠区） ───

    def show_quota(self):
        """托盘左键 / 菜单「查看额度」：唤回 HUD 并展开额度区。

        面板隐藏时走 set_hud_visible(True)，同步托盘复选框与配置，
        避免"面板显示了但配置仍是隐藏"的状态分裂。
        """
        if not self.hud.isVisible():
            self.set_hud_visible(True)
        self.hud.open_quota()
        self.hud.raise_()

    def show_settings(self):
        dlg = SettingsDialog()
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            old_oc = resolve_log_dir(self.config)
            old_dsh = resolve_dsh_dir(self.config)
            self.config = load_config()
            self._start_timer()
            self._apply_hud()
            if (resolve_log_dir(self.config) != old_oc
                    or resolve_dsh_dir(self.config) != old_dsh):
                self._start_watcher()
            QTimer.singleShot(500, self.refresh)

    # ─── 托盘事件 / 退出 ───

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_quota()

    def _quit(self):
        self.timer.stop()
        self._stop_watcher()
        try:
            if self._quota_thread and self._quota_thread.isRunning():
                self._quota_thread.quit()
                self._quota_thread.wait(2000)
        except RuntimeError:
            pass
        self.hud.close()
        self.tray.hide()
        self.app.quit()
