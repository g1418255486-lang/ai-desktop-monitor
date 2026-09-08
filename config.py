import json
import os
import base64


APP_NAME = "ai-desktop-monitor"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

PLATFORMS_CFG = {
    "zhipu": {
        "name": "智谱 (open.bigmodel.cn)",
    },
    "zai": {
        "name": "Z.ai (api.z.ai)",
    },
}

# opencode 默认日志目录（Windows 下 opencode 同样使用该路径）
DEFAULT_LOG_DIR = os.path.join(
    os.path.expanduser("~"), ".local", "share", "opencode", "log"
)

# DeepSeek Harness 默认会话目录
DEFAULT_DSH_DIR = os.path.join(
    os.path.expanduser("~"), ".dsh", "sessions"
)

DEFAULT_CONFIG = {
    "api_key": "",
    "platform": "zhipu",
    "refresh_interval": 300,
    # 空字符串 = 自动检测 DEFAULT_LOG_DIR
    "opencode_log_dir": "",
    # 空字符串 = 自动检测 DEFAULT_DSH_DIR
    "dsh_sessions_dir": "",
    "notify_on_attention": True,
    # 悬浮状态面板（HUD）
    "show_hud": True,
    "hud_slots": 3,
}


def resolve_log_dir(cfg: dict) -> str:
    custom = (cfg.get("opencode_log_dir") or "").strip()
    return custom or DEFAULT_LOG_DIR


def resolve_dsh_dir(cfg: dict) -> str:
    custom = (cfg.get("dsh_sessions_dir") or "").strip()
    return custom or DEFAULT_DSH_DIR


def _encode(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _decode(text: str) -> str:
    return base64.b64decode(text.encode("ascii")).decode("utf-8")


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if cfg.get("api_key"):
                try:
                    cfg["api_key"] = _decode(cfg["api_key"])
                except Exception:
                    pass
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> bool:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        save_data = dict(cfg)
        if save_data.get("api_key"):
            save_data["api_key"] = _encode(save_data["api_key"])
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False)
        return True
    except (OSError, IOError):
        return False
