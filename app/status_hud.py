"""悬浮 Agent 状态 + 额度：两块独立顶层窗口（全息堆叠）。

- 状态面板（主窗口，常驻）：逐会话槽位 + 总体状态芯片 + QUOTA 折叠条
- 额度面板（独立窗口，默认隐藏）：点击折叠条/双击在状态面板上方弹出，
  水平错位 + 反向切角 + 缝隙能量线，真正的两个窗口 —— 状态窗口尺寸
  永不变化，因此既无 resize 残影，按钮/状态区位置也物理上不可能移动。

风格：切角面板 + 扫描线纹理 + 霓虹配色。
"""

from datetime import datetime

from PySide6.QtWidgets import QWidget, QMenu
from PySide6.QtGui import (
    QPainter, QColor, QPen, QFont, QFontMetrics, QPainterPath,
)
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF

from app.theme import (
    menu_qss, TEXT_HEADING, TEXT_SECONDARY, BORDER_WARM, ERROR,
    mono_font as _mono_font,
    bar_color as _theme_bar_color,
)
from services.agent_watcher import (
    STATE_NEEDS_ATTENTION, STATE_RUNNING, STATE_COMPLETED, STATE_DISCONNECTED,
)
from services.quota_service import UsageData

# ─── 赛博朋克配色 ───
CYAN = "#00e5ff"        # 运行（霓虹青）
MAGENTA = "#ff2e88"     # 需要关注（霓虹品红）
GREEN = "#00e676"       # 完成（终端绿）
PANEL_BG = "#0c1210"
PANEL_BG_2 = "#0e1615"  # 额度面板底色（比状态面板微亮偏青）
PANEL_EDGE = "#3d5247"
SLOT_BG = "#111a16"
SLOT_BG_DIM = "#0f1714"
FAINT = "#2a3730"
DIM = "#5f7268"

_TAG = {
    STATE_NEEDS_ATTENTION: "ALERT",
    STATE_RUNNING: "RUN",
    STATE_COMPLETED: "DONE",
    STATE_DISCONNECTED: "--",
}
_TAG_COLOR = {
    STATE_NEEDS_ATTENTION: MAGENTA,
    STATE_RUNNING: CYAN,
    STATE_COMPLETED: GREEN,
    STATE_DISCONNECTED: DIM,
}

# ─── 布局 ───
M = 8         # 外边距
HEAD_H = 24   # 头部高
SLOT_H = 28   # 槽高
SLOT_GAP = 4  # 槽距
FOOT_H = 18   # 状态底部计数高
HUD_W = 248   # 状态面板宽
CORNER = 10   # 右上切角尺寸（状态面板）

QUOTA_TOGGLE_H = 20   # 额度折叠条高
Q_ROW_LABEL = 14      # 额度档：标签/百分比行高
Q_ROW_BAR = 8         # 额度档：进度条高
Q_ROW_RESET = 11      # 额度档：重置时间行高
Q_SEGMENTS = 24       # 进度条分段数

GAP = 7           # 两窗口间缝隙
QUOTA_INSET = 7   # 额度窗口水平错位量
QP_W = HUD_W - 2 * QUOTA_INSET   # 额度窗口宽


def panel_path(w, h, x=0.0, y=0.0, corner=CORNER, corner_tl=False) -> QPainterPath:
    """切角面板路径。corner_tl=True 切左上角（额度窗口），否则切右上角。"""
    path = QPainterPath()
    if corner_tl:
        path.moveTo(x + 0.5 + corner, y + 0.5)
        path.lineTo(x + w - 0.5, y + 0.5)
        path.lineTo(x + w - 0.5, y + h - 0.5)
        path.lineTo(x + 0.5, y + h - 0.5)
        path.lineTo(x + 0.5, y + 0.5 + corner)
    else:
        path.moveTo(x + 0.5, y + 0.5)
        path.lineTo(x + w - 0.5 - corner, y + 0.5)
        path.lineTo(x + w - 0.5, y + 0.5 + corner)
        path.lineTo(x + w - 0.5, y + h - 0.5)
        path.lineTo(x + 0.5, y + h - 0.5)
    path.closeSubpath()
    return path


def paint_panel_base(p: QPainter, path: QPainterPath, bg: str):
    """面板底色 + 描边 + 扫描线纹理（裁剪进面板形状）。"""
    p.fillPath(path, QColor(bg))
    p.setPen(QPen(QColor(PANEL_EDGE), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.save()
    p.setClipPath(path)
    p.setPen(QPen(QColor(255, 255, 255, 8), 1))
    br = path.boundingRect()
    for y in range(int(br.top()), int(br.bottom()) + 1, 3):
        p.drawLine(int(br.left()), y, int(br.right()), y)
    p.restore()


def _fmt_reset(ts) -> str:
    if not ts:
        return ""
    try:
        dt = datetime.fromtimestamp(ts / 1000)
        return f"RESET {dt:%m/%d %H:%M}"
    except Exception:
        return ""


# ══════════════════════════════════════════
#  额度窗口（独立顶层，悬浮在状态窗口上方）
# ══════════════════════════════════════════

class QuotaPanel(QWidget):
    def __init__(self):
        super().__init__(None)
        self._quota: UsageData = None
        self._notes = []

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(QP_W, self.content_h() + M)

    # ─── 数据 ───

    def update_data(self, quota: UsageData):
        self._quota = quota
        self._recalc()

    def update_notes(self, notes):
        self._notes = list(notes)
        self._recalc()

    def content_h(self):
        h = 2
        q = self._quota
        if self._has_data():
            h += 2 * (Q_ROW_LABEL + 2 + Q_ROW_BAR + 2 + Q_ROW_RESET) + 8
        else:
            h += Q_ROW_LABEL + 4
        if q is not None and q.error:
            h += 14
        if self._notes:
            h += 13 * (1 if len(self._notes) <= 1 else 2)
        return h

    def _has_data(self):
        q = self._quota
        return q is not None and (q.token_5h_pct is not None or q.token_weekly_pct is not None)

    def _recalc(self):
        """高度自适应；可见时保持底边不动（向上伸缩）。"""
        nh = self.content_h() + M
        old_h = self.height()
        self.setFixedSize(QP_W, nh)
        if old_h > 0 and nh != old_h and self.isVisible():
            self.move(self.x(), self.y() - (nh - old_h))
        self.update()

    # ─── 弹出定位：贴在状态窗口正上方（放不下则落到下方） ───

    def popup_above(self, status: QWidget):
        geo = status.frameGeometry()
        screen = status.screen().availableGeometry()
        x = geo.x() + QUOTA_INSET
        y = geo.y() - GAP - self.height()
        if y < screen.top():
            y = geo.bottom() + 1 + GAP
        self.move(x, y)
        self.show()
        self.raise_()

    # ─── 绘制 ───

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        # 显式清底，杜绝任何旧帧残留
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillRect(0, 0, w, h, Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

        paint_panel_base(p, panel_path(w, h, corner_tl=True), PANEL_BG_2)
        self._paint_content(p)
        p.end()

    def _paint_content(self, p):
        qx, qw = M, QP_W - 2 * M
        y = M
        q = self._quota

        if not self._has_data():
            p.setFont(_mono_font(9))
            p.setPen(QColor(DIM))
            p.drawText(QRectF(qx, y, qw, Q_ROW_LABEL + 4),
                       Qt.AlignmentFlag.AlignCenter, "· NO QUOTA DATA ·")
            y += Q_ROW_LABEL + 4
        else:
            bars = []
            if q.token_5h_pct is not None:
                bars.append(("TOKEN · 5H", q.token_5h_pct, q.token_5h_reset))
            if q.token_weekly_pct is not None:
                bars.append(("WEEKLY", q.token_weekly_pct, q.token_weekly_reset))
            for i, (label, pct, reset) in enumerate(bars):
                y = self._paint_bar(p, y, label, pct, reset, qx, qw)
                if i < len(bars) - 1:
                    y += 8

        if q is not None and q.error:
            f9 = _mono_font(9)
            p.setFont(f9)
            fm = QFontMetrics(f9)
            txt = fm.elidedText(f"ERR: {q.error}", Qt.TextElideMode.ElideRight, qw)
            p.setPen(QColor(ERROR))
            p.drawText(QRectF(qx, y, qw, 12),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, txt)
            y += 14

        if self._notes:
            f8 = _mono_font(8)
            p.setFont(f8)
            fm = QFontMetrics(f8)
            txt = fm.elidedText(" · ".join(self._notes), Qt.TextElideMode.ElideRight, qw)
            p.setPen(QColor(DIM))
            p.drawText(QRectF(qx, y, qw, 11),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, txt)

    def _paint_bar(self, p, y, label, pct, reset, qx, qw):
        color = _theme_bar_color(pct)

        f9 = _mono_font(9, QFont.Weight.Bold, 140)
        p.setFont(f9)
        p.setPen(QColor(DIM))
        p.drawText(QRectF(qx, y, qw, Q_ROW_LABEL),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        p.setFont(_mono_font(10, QFont.Weight.Bold))
        p.setPen(color)
        p.drawText(QRectF(qx, y, qw, Q_ROW_LABEL),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{pct:.0f}%")
        y += Q_ROW_LABEL + 2

        bar_rect = QRectF(qx, y, qw, Q_ROW_BAR)
        gap = 2
        seg_w = (bar_rect.width() - gap * (Q_SEGMENTS - 1)) / Q_SEGMENTS
        filled = round(pct / 100 * Q_SEGMENTS)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(Q_SEGMENTS):
            x = bar_rect.left() + i * (seg_w + gap)
            p.setBrush(color if i < filled else QColor(BORDER_WARM))
            p.drawRoundedRect(QRectF(x, bar_rect.top(), seg_w, Q_ROW_BAR), 1, 1)
        y += Q_ROW_BAR + 2

        if reset:
            p.setFont(_mono_font(8))
            p.setPen(QColor(DIM))
            p.drawText(QRectF(qx, y, qw, Q_ROW_RESET),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       _fmt_reset(reset))
        y += Q_ROW_RESET
        return y


# ══════════════════════════════════════════
#  状态窗口（主窗口，尺寸恒定不 resize）
# ══════════════════════════════════════════

class StatusHud(QWidget):
    def __init__(self, controller):
        """controller 需提供：set_hud_visible(bool) / show_settings()"""
        super().__init__(None)
        self._controller = controller
        self._payload = None
        self._quota: UsageData = None     # 仅用于折叠条右侧 5h%
        self._slots = 3
        self._frame = 0
        self._drag_pos = None
        self._placed = False

        # 额度独立窗口
        self._quota_win = QuotaPanel()

        # 动画帧计时器（小控件，整帧重绘开销可忽略）
        self._tick = QTimer(self)
        self._tick.setInterval(400)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 尺寸恒定：状态窗口从不 resize —— 从根源上无 resize 残影
        self.setFixedSize(HUD_W, self._status_h() + M)

    # ─── 对外接口 ───

    def set_slots(self, n: int):
        n = max(1, min(6, int(n)))
        if n == self._slots:
            return
        self._slots = n
        self.setFixedSize(HUD_W, self._status_h() + M)
        self.update()

    def update_payload(self, payload: dict):
        self._payload = payload or {}
        self._quota_win.update_notes(self._notes())
        self.update()

    def update_quota(self, quota: UsageData):
        self._quota = quota
        self._quota_win.update_data(quota)
        self.update()

    def toggle_quota(self):
        if self._quota_win.isVisible():
            self._quota_win.hide()
        else:
            self._quota_win.popup_above(self)

    def open_quota(self):
        """确保额度窗口弹出（供托盘左键/菜单调用）。"""
        if not self._quota_win.isVisible():
            self.toggle_quota()

    # ─── 布局 ───

    def _toggle_top(self):
        """折叠条 y：头部正下方。"""
        return M + HEAD_H + 2

    def _slots_top(self):
        return self._toggle_top() + QUOTA_TOGGLE_H + 4

    def _status_h(self):
        """状态区底（footer 之后）。"""
        return self._slots_top() + self._slots * SLOT_H + (self._slots - 1) * SLOT_GAP + 6 + FOOT_H

    def _toggle_rect(self) -> QRectF:
        """折叠条矩形（实时计算，绘制与命中共用同一来源）。"""
        return QRectF(M, self._toggle_top(), HUD_W - 2 * M, QUOTA_TOGGLE_H)

    def _on_tick(self):
        self._frame = (self._frame + 1) % 4
        self.update()

    def _sessions(self):
        return (self._payload or {}).get("sessions") or []

    def _notes(self):
        sources = (self._payload or {}).get("sources") or {}
        notes = []
        if (sources.get("opencode") or {}).get("dir_exists") is False:
            notes.append("opencode 日志目录不存在")
        dsh = sources.get("dsh") or {}
        if dsh.get("dir_exists") is False:
            notes.append("DSH 会话目录不存在")
        if dsh.get("error"):
            notes.append(f"DSH: {dsh['error']}")
        return notes

    # ─── 绘制 ───

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        # 显式清底，杜绝任何旧帧残留
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillRect(0, 0, w, h, Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

        paint_panel_base(p, panel_path(w, h), PANEL_BG)
        self._paint_header(p)
        self._paint_quota_toggle(p)
        self._paint_slots(p)
        self._paint_footer(p)
        p.end()

    def _paint_header(self, p):
        rect = QRectF(M, M, HUD_W - 2 * M, HEAD_H - 8)

        p.setFont(_mono_font(11, QFont.Weight.Bold, 130))
        p.setPen(QColor(TEXT_HEADING))
        p.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "AGENT//STATUS")

        overall = (self._payload or {}).get("state", STATE_DISCONNECTED)
        color = QColor(_TAG_COLOR.get(overall, DIM))
        if overall == STATE_NEEDS_ATTENTION and self._frame % 2:
            color = QColor(DIM)  # 告警闪烁
        p.setFont(_mono_font(11, QFont.Weight.Bold))
        p.setPen(color)
        p.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   f"◉ {_TAG.get(overall, '--')}")

        p.setPen(QPen(QColor(FAINT), 1))
        dy = M + HEAD_H - 3
        p.drawLine(M, dy, HUD_W - M, dy)

    def _paint_slots(self, p):
        sessions = self._sessions()
        top = self._slots_top()
        for i in range(self._slots):
            y = top + i * (SLOT_H + SLOT_GAP)
            rect = QRectF(M, y, HUD_W - 2 * M, SLOT_H)
            if i < len(sessions):
                self._paint_session(p, rect, sessions[i])
            else:
                self._paint_standby(p, rect)

    def _paint_session(self, p, rect: QRectF, rec: dict):
        state = rec.get("state", STATE_DISCONNECTED)
        color = QColor(_TAG_COLOR.get(state, DIM))

        # 槽底 + 边框（告警闪烁品红边）
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(SLOT_BG))
        p.drawRect(rect)
        border = QColor(MAGENTA) if (state == STATE_NEEDS_ATTENTION and self._frame % 2) else QColor(FAINT)
        p.setPen(QPen(border, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))

        # 左侧霓虹状态条（运行时脉冲）
        bar = QColor(color)
        if state == STATE_RUNNING and self._frame % 2:
            bar.setAlpha(140)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bar)
        p.drawRect(QRectF(rect.left() + 1, rect.top() + 4, 3, rect.height() - 8))

        # 来源标签 [OC] / [DSH]
        f9 = _mono_font(9)
        p.setFont(f9)
        fm9 = QFontMetrics(f9)
        kind = f"[{rec.get('kind', '')}]"
        p.setPen(QColor(DIM))
        p.drawText(QRectF(rect.left() + 10, rect.top(), fm9.horizontalAdvance(kind), rect.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, kind)

        # 名称（+ 待决徽标，超长省略）
        x = rect.left() + 10 + fm9.horizontalAdvance(kind) + 5
        f10 = _mono_font(10)
        p.setFont(f10)
        fm10 = QFontMetrics(f10)
        state_text = self._state_text(state)
        right_w = fm10.horizontalAdvance(state_text) + 8
        avail = rect.right() - 8 - right_w - x

        name = rec.get("name", "")
        q = rec.get("questions", 0)
        pp = rec.get("permissions", 0)
        badge = ""
        if q and pp:
            badge = f"  Q{q}+P{pp}"
        elif q:
            badge = f"  Q{q}"
        elif pp:
            badge = f"  P{pp}"

        elided = fm10.elidedText(name + badge, Qt.TextElideMode.ElideRight, int(max(10, avail)))
        p.setPen(QColor(TEXT_HEADING if state != STATE_COMPLETED else TEXT_SECONDARY))
        p.drawText(QRectF(x, rect.top(), avail, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)

        # 右侧状态标签
        p.setPen(color)
        p.drawText(QRectF(rect.right() - 8 - right_w, rect.top(), right_w, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, state_text)

    def _paint_standby(self, p, rect: QRectF):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(SLOT_BG_DIM))
        p.drawRect(rect)
        p.setPen(QPen(QColor(FAINT), 1, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
        p.setFont(_mono_font(9))
        p.setPen(QColor(DIM))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "· STANDBY ·")

    def _paint_footer(self, p):
        sources = (self._payload or {}).get("sources") or {}
        oc = (sources.get("opencode") or {}).get("active", 0)
        dsh = (sources.get("dsh") or {}).get("active", 0)
        total = len(self._sessions())
        shown = min(self._slots, total)

        f9 = _mono_font(9)
        p.setFont(f9)
        rect = QRectF(M, self._status_h() - FOOT_H + 3, HUD_W - 2 * M, FOOT_H)
        p.setPen(QColor(DIM))
        p.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   f":: OC {oc} · DSH {dsh}")
        if total > shown:
            p.setPen(QColor(TEXT_SECONDARY))
            p.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       f"+{total - shown} MORE")

    def _paint_quota_toggle(self, p):
        """折叠条（按钮）：头部正下方常驻。▾/▸ QUOTA + 5h%"""
        toggle = self._toggle_rect()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(SLOT_BG))
        p.drawRoundedRect(toggle, 2, 2)
        p.setFont(_mono_font(9, QFont.Weight.Bold, 140))
        p.setPen(QColor(TEXT_HEADING))
        arrow = "\u25be" if self._quota_win.isVisible() else "\u25b8"   # ▾ / ▸
        p.drawText(toggle.adjusted(8, 0, -8, 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   f"{arrow} QUOTA")
        q = self._quota
        if q is not None and q.token_5h_pct is not None:
            p.setPen(QColor(_theme_bar_color(q.token_5h_pct)))
            p.drawText(toggle.adjusted(8, 0, -8, 0),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       f"{q.token_5h_pct:.0f}%")

    def _state_text(self, state: str) -> str:
        tag = _TAG.get(state, "--")
        if state == STATE_RUNNING:
            return tag + "." * (self._frame + 1)   # RUN. RUN.. RUN...
        if state == STATE_NEEDS_ATTENTION:
            return "!" + tag
        return tag

    # ─── 交互 ───

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            # 命中额度折叠条 → 切换额度窗口（不启动拖拽）
            if self._toggle_rect().contains(QPointF(pos)):
                self.toggle_quota()
                event.accept()
                return
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            # 拖动状态窗口时，额度窗口跟随
            if self._quota_win.isVisible():
                self._quota_win.popup_above(self)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        # 单击折叠条已 toggle 一次，双击再 toggle 会"开了又关"——直接吞掉
        if self._toggle_rect().contains(QPointF(pos)):
            event.accept()
            return
        self.toggle_quota()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(menu_qss())

        quota = menu.addAction("收起额度" if self._quota_win.isVisible() else "显示额度")
        quota.triggered.connect(self.toggle_quota)

        menu.addSeparator()
        hide = menu.addAction("隐藏面板")
        hide.triggered.connect(lambda: self._controller.set_hud_visible(False))

        settings = menu.addAction("设置")
        settings.triggered.connect(self._controller.show_settings)

        menu.exec(event.globalPos())

    def showEvent(self, event):
        super().showEvent(event)
        if not self._placed:
            self._placed = True
            geo = self.screen().availableGeometry()
            self.move(geo.right() - self.width() - 20, geo.bottom() - self.height() - 120)

    def hideEvent(self, event):
        # 状态窗口隐藏时，额度窗口一并收起
        self._quota_win.hide()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._quota_win.close()
        super().closeEvent(event)
