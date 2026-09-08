"""DeepSeek Harness 会话 transcript 解析。

DSH 会话存储为 ~/.dsh/sessions/<workspace>/session-<id>/session.jsonl.zstd
（多个 zstd frame 追加写入的 JSONL 事件流）。每个轮询周期对有变化的
活跃文件做全量解压 + 轻量过滤解析，得出该会话的状态：

- pending_questions: ask_user_question 工具调用尚无对应 tool/result
- pending_permissions: approval/asked 尚无对应 approval/decided（按 id 配对）
- is_busy: 最后一次 turn/start 晚于最后一次 turn/end
- title: 最后一条 session/title 事件的标题
"""

import json

try:
    import zstandard as _zstd
    HAS_ZSTD = True
except ImportError:
    _zstd = None
    HAS_ZSTD = False

# 感兴趣的事件（在去空格后的行上做子串过滤，跳过海量 chunk 行）
_KEYS = (
    '"type":"turn/start"',
    '"type":"turn/end"',
    '"type":"tool/call"',
    '"type":"tool/result"',
    '"type":"approval/asked"',
    '"type":"approval/decided"',
    '"type":"session/title"',
)

ASK_TOOL_NAMES = {"ask_user_question"}


class DshSessionState:
    """与 opencode 的 LogTailer 属性保持同名，便于聚合复用。"""

    __slots__ = ("is_busy", "pending_questions", "pending_permissions", "title")

    def __init__(self):
        self.is_busy = False
        self.pending_questions = 0
        self.pending_permissions = 0
        self.title = ""


def _decompress(path: str) -> str:
    with open(path, "rb") as f:
        reader = _zstd.ZstdDecompressor().stream_reader(f, read_across_frames=True)
        chunks = []
        while True:
            c = reader.read(262144)
            if not c:
                break
            chunks.append(c)
    return b"".join(chunks).decode("utf-8", "replace")


def parse_session(path: str) -> DshSessionState:
    """全量解析一个 session.jsonl.zstd。IO/解码异常向上抛出由调用方兜底。"""
    st = DshSessionState()

    last_turn_start = -1
    last_turn_end = -1
    ask_calls = set()        # 未闭环的 ask_user_question callId
    open_approvals = set()   # 未决定的 approval id

    for line in _decompress(path).splitlines():
        if not any(k in line.replace(" ", "") for k in _KEYS):
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        etype = ev.get("type")
        data = ev.get("data") or {}
        seq = ev.get("seq") or 0

        if etype == "turn/start":
            if seq > last_turn_start:
                last_turn_start = seq
        elif etype == "turn/end":
            if seq > last_turn_end:
                last_turn_end = seq
        elif etype == "tool/call":
            if data.get("name") in ASK_TOOL_NAMES:
                call_id = data.get("callId")
                if call_id:
                    ask_calls.add(call_id)
        elif etype == "tool/result":
            src = ((data.get("message") or {}).get("source") or {})
            call_id = src.get("callId")
            if call_id:
                ask_calls.discard(call_id)
        elif etype == "approval/asked":
            aid = data.get("id")
            if aid:
                open_approvals.add(aid)
        elif etype == "approval/decided":
            open_approvals.discard(data.get("id"))
        elif etype == "session/title":
            if data.get("title"):
                st.title = data["title"]

    st.is_busy = last_turn_start > last_turn_end
    st.pending_questions = len(ask_calls)
    st.pending_permissions = len(open_approvals)
    return st
