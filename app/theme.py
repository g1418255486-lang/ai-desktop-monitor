from PySide6.QtGui import QColor

# ─── terminal HUD design tokens ───

# accent terminal green
PRIMARY = "#00e676"

# text (green-tinted grays)
TEXT_HEADING = "#e8f5ec"
TEXT_BODY = "#9fb5a6"
TEXT_SECONDARY = "#5f7268"

# surfaces (softened dark)
BG = "#151d19"
BG_CARD = "#1c2621"

# borders
BORDER_WARM = "#2a3730"
BORDER_STRONG = "#35453c"

# status (bright for dark bg)
SUCCESS = "#00e676"
WARNING = "#ffb300"
ERROR = "#ff5252"

# corner radius (sharp, technical)
RADIUS = 6

# fonts
FONT_FAMILY = "Segoe UI Variable Text, Microsoft YaHei UI, Segoe UI, Microsoft YaHei"
MONO_FAMILY = "Cascadia Mono, JetBrains Mono, Consolas, Courier New"

# ─── agent 状态标签（悬浮 HUD 的配色见 app/status_hud.py 霓虹色板） ───
# 键与 services.agent_watcher 中的 STATE_* 常量保持一致
STATE_LABELS = {
    "needs_attention": "需要关注",
    "running": "运行中",
    "completed": "已完成",
    "disconnected": "未连接",
}


def _make_font(family_list: str, pixel: int, weight, spacing: int = 0):
    from PySide6.QtGui import QFont, QFontDatabase
    f = QFont()
    installed = QFontDatabase.families()
    families = [n for n in family_list.split(",") if n in installed]
    f.setFamilies(families + ["Consolas", "Segoe UI", "Microsoft YaHei UI"])
    f.setPixelSize(pixel)
    try:
        f.setWeight(QFont.Weight(weight))
    except Exception:
        f.setWeight(QFont.Weight.Normal)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, spacing)
    return f


def qss_font(size: int, weight: int = 400) -> str:
    return f'font-family:"{FONT_FAMILY}";font-size:{size}px;font-weight:{weight};'


def mono_font(pixel: int, weight=400, spacing: int = 0):
    """Monospace font for numbers/technical labels."""
    return _make_font(MONO_FAMILY, pixel, weight, spacing)


def bar_color(pct: float) -> QColor:
    """额度余量色阶：≥75% 红、≥50% 橙、≥25% 绿、其余亮绿。"""
    if pct >= 75:
        return QColor(ERROR)
    elif pct >= 50:
        return QColor(WARNING)
    elif pct >= 25:
        return QColor(PRIMARY)
    return QColor(SUCCESS)


def menu_qss() -> str:
    """Themed QMenu stylesheet for the tray context menu."""
    return f"""
    QMenu {{
        {qss_font(12, 500)}
        background: {BG};
        color: {TEXT_BODY};
        border: 1px solid {BORDER_STRONG};
        border-radius: {RADIUS}px;
        padding: 6px;
    }}
    QMenu::item {{
        padding: 7px 26px 7px 16px;
        border-radius: 4px;
    }}
    QMenu::item:selected {{
        background: {BG_CARD};
        color: {PRIMARY};
    }}
    QMenu::item:disabled {{
        color: {TEXT_SECONDARY};
    }}
    QMenu::separator {{
        height: 1px;
        background: {BORDER_WARM};
        margin: 5px 10px;
    }}
    """
