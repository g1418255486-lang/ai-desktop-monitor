"""悬浮 Agent 状态 + 额度面板（赛博朋克 Terminal HUD）。

常驻置顶唯一窗口：
- 状态区（默认显示）：逐会话槽位（哪个在跑/在等你/已完成）+ 总体状态芯片 + 来源计数
- 额度区（默认收起）：折叠条按钮控制展开/收起，TOKEN·5H / WEEKLY 分段方块
  进度条（余量色阶，与旧版额度弹窗一致）+ 重置时间 + 错误行

风格：切角面板 + 扫描线纹理 + 霓虹配色。
交互：拖拽定位、双击切换额度区、右键菜单、点击 QUOTA 折叠条展开/收起。
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
HUD_W = 248   # 面板宽
CORNER = 10   # 右上切角尺寸（状态面板）

QUOTA_TOGGLE_H = 20   # 额度折叠条高
Q_ROW_LABEL = 14      # 额度档：标签/百分比行高
Q_ROW_BAR = 8         # 额度档：进度条高
Q_ROW_RESET = 11      # 额度档：重置时间行高
Q_SEGMENTS = 24       # 进度条分段数

# ─── 双面板堆叠 ───
GAP = 7           # 两面板间透明缝隙（含能量连接线）
QUOTA_INSET = 7   # 额度面板水平内缩（与状态面板错位，全息堆叠感）
PANEL_BG_2 = "#0e1615"   # 额度面板底色（比状态面板微亮偏青）


class StatusHud(QWidget):
    def __init__(self, controller):
        """controller 需提供：set_hud_visible(bool) / show_settings()"""
        super().__init__(None)
        self._controller = controller
        self._payload = None
        self._quota: UsageData = None
        self._quota_open = False          # 默认只显示状态
        self._quota_toggle_rect = None    # 折叠条命中区域
        self._slots = 3
        self._frame = 0
        self._drag_pos = None
        self._placed = False

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
        self._recalc_size()

    # ─── 对外接口 ───

    def set_slots(self, n: int):
        n = max(1, min(6, int(n)))
        if n == self._slots:
            return
        self._slots = n
        self._recalc_size()
        self.update()

    def update_payload(self, payload: dict):
        self._payload = payload or {}
        self._recalc_size()
        self.update()

    def update_quota(self, quota: UsageData):
        self._quota = quota
        self._recalc_size()
        self.update()

    def toggle_quota(self):
        self._quota_open = not self._quota_open
        self._recalc_size()
        self.update()

    def open_quota(self):
        """确保展开（供托盘左键/菜单调用，配合 controller 保证可见）。"""
        if not self._quota_open:
            self.toggle_quota()

    # ─── 尺寸与动画 ───

    def _toggle_top(self):
        """折叠条 y：头部正下方（常驻，方便点按）。"""
        return M + HEAD_H + 2

    def _slots_top(self):
        return self._toggle_top() + QUOTA_TOGGLE_H + 4

    def _status_h(self):
        """状态区底（footer 之后）。"""
        return self._slots_top() + self._slots * SLOT_H + (self._slots - 1) * SLOT_GAP + 6 + FOOT_H

    def _quota_content_h(self):
        """顶部额度内容高（画在 y=M 起）。行高常量与 _paint_quota_bar 共用。"""
        h = 2
        q = self._quota
        if self._has_quota_data():
            h += 2 * (Q_ROW_LABEL + 2 + Q_ROW_BAR + 2 + Q_ROW_RESET) + 8
        else:
            h += Q_ROW_LABEL + 4
        if q is not None and q.error:
            h += 14
        notes = self._notes()
        if notes:
            h += 13 * (1 if len(notes) <= 1 else 2)
        return h

    def _has_quota_data(self):
        q = self._quota
        return q is not None and (q.token_5h_pct is not None or q.token_weekly_pct is not None)

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

    def _quota_panel_h(self):
        """额度面板自身高度（独立窗口感的一整块）。"""
        return self._quota_content_h() + M

    def _offset(self):
        """展开时状态区整体下移量 = 额度面板高 + 面板间缝隙。

        额度画成独立面板悬浮在上方（水平错位 + 反向切角），
        窗口顶边向上扩展（底边锚定），状态面板屏幕绝对位置不变。"""
        return (self._quota_panel_h() + GAP) if self._quota_open else 0

    def _recalc_size(self):
        # 展开时顶部叠加额度面板 + 缝隙（底边锚定向上扩展）
        h = self._offset() + self._status_h() + M
        old_h = self.height()
        self.setFixedSize(HUD_W, h)
        # 底边锚定：高度变化时顶边向上/向下补偿，
        # 面板贴右下角放置时展开不会伸出屏幕底
        if old_h > 0 and h != old_h and self.isVisible():
            self.move(self.x(), self.y() - (h - old_h))

    def _on_tick(self):
        self._frame = (self._frame + 1) % 4
        self.update()

    def _sessions(self):
        return (self._payload or {}).get("sessions") or []

    # ─── 绘制 ───

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()

        if self._quota_open:
            # ─── 额度面板（独立悬浮块：左上切角 + 水平错位） ───
            qh = self._quota_panel_h()
            qpath = self._panel_path(HUD_W - 2 * QUOTA_INSET, qh,
                                     x=QUOTA_INSET, y=0, corner_tl=True)
            self._paint_panel_base(p, qpath, PANEL_BG_2)
            self._paint_quota_content(p)
            # 面板缝隙间的能量连接线
            gy0 = qh
            p.setPen(QPen(QColor(FAINT), 1, Qt.PenStyle.DashLine))
            p.drawLine(HUD_W // 2, gy0 + 1, HUD_W // 2, gy0 + GAP - 1)

        # ─── 状态面板（主面板：右上切角） ───
        spath = self._panel_path(w, self._status_h() + M, y=self._offset())
        self._paint_panel_base(p, spath, PANEL_BG)
        self._paint_header(p)
        self._paint_quota_toggle(p)
        self._paint_slots(p)
        self._paint_footer(p)
        p.end()

    def _paint_panel_base(self, p, path: QPainterPath, bg: str):
        """面板底色 + 描边 + 扫描线纹理（裁剪进面板形状）。"""
        p.fillPath(path, QColor(bg))
        p.setPen(QPen(QColor(PANEL_EDGE), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.save()
        p.setClipPath(path)
        p.setPen(QPen(QColor(255, 255, 255, 8), 1))
        for y in range(int(path.boundingRect().top()), int(path.boundingRect().bottom()) + 1, 3):
            p.drawLine(int(path.boundingRect().left()), y, int(path.boundingRect().right()), y)
        p.restore()

    @staticmethod
    def _panel_path(w, h, x=0.0, y=0.0, corner=CORNER, corner_tl=False) -> QPainterPath:
        """切角面板路径。corner_tl=True 时切左上角（额度面板），否则切右上角。"""
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

    def _paint_header(self, p):
        off = self._offset()
        rect = QRectF(M, M + off, HUD_W - 2 * M, HEAD_H - 8)

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
        dy = M + off + HEAD_H - 3
        p.drawLine(M, dy, HUD_W - M, dy)

    def _paint_slots(self, p):
        sessions = self._sessions()
        top = self._slots_top() + self._offset()
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
        rect = QRectF(M, self._status_h() + self._offset() - FOOT_H + 3, HUD_W - 2 * M, FOOT_H)
        p.setPen(QColor(DIM))
        p.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   f":: OC {oc} · DSH {dsh}")
        if total > shown:
            p.setPen(QColor(TEXT_SECONDARY))
            p.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       f"+{total - shown} MORE")

    # ─── 额度区 ───

    def _paint_quota_toggle(self, p):
        """折叠条（按钮）：头部正下方常驻（含 offset 后屏幕位置固定）。▾/▸ QUOTA + 5h%"""
        y = self._toggle_top() + self._offset()
        toggle = QRectF(M, y, HUD_W - 2 * M, QUOTA_TOGGLE_H)
        self._quota_toggle_rect = toggle
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(SLOT_BG))
        p.drawRoundedRect(toggle, 2, 2)
        p.setFont(_mono_font(9, QFont.Weight.Bold, 140))
        p.setPen(QColor(TEXT_HEADING))
        arrow = "\u25be" if self._quota_open else "\u25b8"   # ▾ / ▸
        p.drawText(toggle.adjusted(8, 0, -8, 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   f"{arrow} QUOTA")
        q = self._quota
        if q is not None and q.token_5h_pct is not None:
            p.setPen(QColor(_theme_bar_color(q.token_5h_pct)))
            p.drawText(toggle.adjusted(8, 0, -8, 0),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       f"{q.token_5h_pct:.0f}%")

    def _paint_quota_content(self, p):
        """额度面板内容：画在独立悬浮面板内（水平随面板内缩）。"""
        qx = M + QUOTA_INSET
        qw = HUD_W - 2 * qx
        y = M
        q = self._quota

        if not self._has_quota_data():
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
                y = self._paint_quota_bar(p, y, label, pct, reset, qx, qw)
                if i < len(bars) - 1:
                    y += 8

        # 错误行
        if q is not None and q.error:
            f9 = _mono_font(9)
            p.setFont(f9)
            fm = QFontMetrics(f9)
            txt = fm.elidedText(f"ERR: {q.error}", Qt.TextElideMode.ElideRight, qw)
            p.setPen(QColor(ERROR))
            p.drawText(QRectF(qx, y, qw, 12),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, txt)
            y += 14

        # 目录/依赖缺失提示
        notes = self._notes()
        if notes:
            f8 = _mono_font(8)
            p.setFont(f8)
            fm = QFontMetrics(f8)
            txt = fm.elidedText(" · ".join(notes), Qt.TextElideMode.ElideRight, qw)
            p.setPen(QColor(DIM))
            p.drawText(QRectF(qx, y, qw, 11),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, txt)

    def _paint_quota_bar(self, p, y, label, pct, reset, qx, qw):
        color = _theme_bar_color(pct)

        # 标签 + 百分比
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

        # 分段方块进度条（24 段，余量色阶）
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

        # 重置时间
        if reset:
            p.setFont(_mono_font(8))
            p.setPen(QColor(DIM))
            p.drawText(QRectF(qx, y, qw, Q_ROW_RESET),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       self._fmt_reset(reset))
        y += Q_ROW_RESET
        return y

    @staticmethod
    def _fmt_reset(ts) -> str:
        if not ts:
            return ""
        try:
            dt = datetime.fromtimestamp(ts / 1000)
            return f"RESET {dt:%m/%d %H:%M}"
        except Exception:
            return ""

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
            # 命中额度折叠条 → 切换展开/收起（不启动拖拽）
            if self._quota_toggle_rect is not None and \
                    self._quota_toggle_rect.contains(QPointF(pos)):
                self.toggle_quota()
                event.accept()
                return
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        # 单击折叠条已 toggle 一次，双击再 toggle 会"开了又关"——直接吞掉
        if self._quota_toggle_rect is not None and \
                self._quota_toggle_rect.contains(QPointF(pos)):
            event.accept()
            return
        self.toggle_quota()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(menu_qss())

        quota = menu.addAction("显示额度" if not self._quota_open else "收起额度")
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
