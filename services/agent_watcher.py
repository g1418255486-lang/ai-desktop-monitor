"""Agent 状态监控：opencode 日志目录 + DSH 会话目录双源聚合。

- opencode：增量 tail *.log（LogTailer，10 分钟活跃阈值）
- DSH：轮询 ~/.dsh/sessions/**/session*.jsonl.zstd，文件变化时全量重解析
  （zstd 多 frame 追加）。有未决提问/审批的会话即使日志陈旧也保持关注，
  避免"正在等你回答"的会话因 10 分钟无写入而消失。

payload 除双源聚合外，还提供逐会话明细 sessions（供悬浮 HUD 分槽位展示）：
会话状态 = 需要关注(提问/审批未决) > 运行中 > 已完成；排序：状态优先级
降序 + 最近活跃降序。两源皆无活动会话时总体为未连接。
"""

import os
import time

from PySide6.QtCore import QObject, Signal

from services.log_tailer import LogTailer
from services import dsh_parser

# 状态常量（app/theme.py 的 STATE_COLORS/STATE_LABELS 与之保持一致）
STATE_DISCONNECTED = "disconnected"
STATE_NEEDS_ATTENTION = "needs_attention"
STATE_RUNNING = "running"
STATE_COMPLETED = "completed"

ACTIVE_THRESHOLD_MIN = 10
RESCAN_SECONDS = 3.0
POLL_SECONDS = 0.3

_PRIORITY = {
    STATE_NEEDS_ATTENTION: 3,
    STATE_RUNNING: 2,
    STATE_COMPLETED: 1,
    STATE_DISCONNECTED: 0,
}


def _state_of(s):
    """单会话状态（LogTailer / DshSessionState 共用同名字段）。"""
    if s.pending_questions > 0 or s.pending_permissions > 0:
        return STATE_NEEDS_ATTENTION
    if s.is_busy:
        return STATE_RUNNING
    return STATE_COMPLETED


def _agg(states):
    """聚合一组会话状态 → (state, active, busy, questions, permissions)。"""
    states = list(states)
    if not states:
        return STATE_DISCONNECTED, 0, 0, 0, 0
    busy = sum(1 for s in states if s.is_busy)
    questions = sum(s.pending_questions for s in states)
    permissions = sum(s.pending_permissions for s in states)
    if questions > 0 or permissions > 0:
        state = STATE_NEEDS_ATTENTION
    elif busy > 0:
        state = STATE_RUNNING
    else:
        state = STATE_COMPLETED
    return state, len(states), busy, questions, permissions


class WatcherWorker(QObject):
    """在 QThread 中持续监控两个来源，状态变化时发出 state_changed(object)。"""

    state_changed = Signal(object)
    finished = Signal()

    def __init__(self, opencode_dir: str, dsh_dir: str):
        super().__init__()
        self._oc_dir = opencode_dir
        self._dsh_dir = dsh_dir
        self._stop = False

    def stop(self):
        self._stop = True

    # ─── 主循环 ───

    def run(self):
        oc_tailers = {}
        dsh_cache = {}   # path -> (mtime, size, DshSessionState)
        last_scan = 0.0
        last_sig = None
        try:
            while not self._stop:
                now = time.time()
                if now - last_scan >= RESCAN_SECONDS:
                    last_scan = now
                    self._sync_opencode(oc_tailers)
                    self._sync_dsh(dsh_cache)
                self._poll_opencode(oc_tailers)
                self._poll_dsh(dsh_cache)

                sig = self._signature(oc_tailers, dsh_cache)
                if sig != last_sig:
                    last_sig = sig
                    self.state_changed.emit(self._payload(oc_tailers, dsh_cache, sig))

                time.sleep(POLL_SECONDS)
        finally:
            for t in oc_tailers.values():
                try:
                    t.close()
                except Exception:
                    pass
            self.finished.emit()

    # ─── opencode 源 ───

    def _sync_opencode(self, tailers: dict):
        if not self._oc_dir or not os.path.isdir(self._oc_dir):
            for t in tailers.values():
                t.close()
            tailers.clear()
            return
        now = time.time()
        try:
            names = os.listdir(self._oc_dir)
        except OSError:
            return
        active = []
        for name in names:
            if not name.endswith(".log"):
                continue
            p = os.path.join(self._oc_dir, name)
            try:
                if now - os.path.getmtime(p) < ACTIVE_THRESHOLD_MIN * 60:
                    active.append(p)
            except OSError:
                continue
        for p in active:
            if p not in tailers:
                try:
                    tailers[p] = LogTailer(p)
                except OSError:
                    pass
        for p in [k for k in tailers if k not in active]:
            tailers.pop(p).close()

    def _poll_opencode(self, tailers: dict):
        for t in list(tailers.values()):
            try:
                t.poll()
            except OSError:
                pass

    # ─── DSH 源 ───

    def _scan_dsh(self):
        """返回 (会话 zstd 路径 -> mtime) 字典；递归扫描。"""
        out = {}
        if not self._dsh_dir or not os.path.isdir(self._dsh_dir):
            return out
        now = time.time()
        for root, _dirs, files in os.walk(self._dsh_dir):
            for name in files:
                # 兼容新旧命名：session.jsonl.zstd（旧）/ session.v3.jsonl.zstd（新）
                if not (name.startswith("session") and name.endswith(".jsonl.zstd")):
                    continue
                p = os.path.join(root, name)
                try:
                    mtime = os.path.getmtime(p)
                except OSError:
                    continue
                if now - mtime < ACTIVE_THRESHOLD_MIN * 60:
                    out[p] = mtime
        return out

    def _sync_dsh(self, cache: dict):
        fresh = self._scan_dsh()
        # 有未决提问/审批的缓存会话即使已过活跃阈值也保留（等待用户响应）
        for p in [k for k, (_m, _s, st) in cache.items()
                  if k not in fresh and st.pending_questions == 0
                  and st.pending_permissions == 0]:
            cache.pop(p)
        for p in fresh:
            if p not in cache:
                cache[p] = (0.0, -1, dsh_parser.DshSessionState())

    def _poll_dsh(self, cache: dict):
        for p in list(cache.keys()):
            try:
                stt = os.stat(p)
                mtime, size = stt.st_mtime, stt.st_size
            except OSError:
                cache.pop(p, None)
                continue
            m, s, st = cache[p]
            if mtime == m and size == s:
                continue  # 未变化，复用缓存
            try:
                st = dsh_parser.parse_session(p)
                cache[p] = (mtime, size, st)
            except Exception:
                # 写入中的半帧等瞬态错误：保留旧状态，下轮重试
                cache[p] = (0.0, -1, st)

    # ─── 逐会话明细 ───

    def _oc_sessions(self, tailers: dict):
        out = []
        for p, t in tailers.items():
            try:
                mtime = os.path.getmtime(p)
            except OSError:
                mtime = 0.0
            name = os.path.basename(p)
            if name.endswith(".log"):
                name = name[:-4]
            out.append(self._session_record("OC", name, t, mtime))
        return out

    def _dsh_sessions(self, cache: dict):
        out = []
        for p, (mtime, _size, st) in cache.items():
            name = st.title or os.path.basename(os.path.dirname(p))
            out.append(self._session_record("DSH", name, st, mtime))
        return out

    @staticmethod
    def _session_record(kind, name, s, mtime):
        return {
            "kind": kind,                     # "OC" / "DSH"
            "name": name,
            "state": _state_of(s),
            "busy": s.is_busy,
            "questions": s.pending_questions,
            "permissions": s.pending_permissions,
            "mtime": mtime,
        }

    @staticmethod
    def _sort_sessions(sessions):
        sessions.sort(key=lambda r: (-_PRIORITY[r["state"]], -r["mtime"]))
        return sessions

    # ─── 聚合与载荷 ───

    def _source_payload(self, state_tuple, dir_exists, error=None, sessions=None):
        state, active, busy, questions, permissions = state_tuple
        return {
            "state": state,
            "active": active,
            "busy": busy,
            "questions": questions,
            "permissions": permissions,
            "dir_exists": dir_exists,
            "error": error,
            "sessions": sessions or [],
        }

    def _signature(self, oc_tailers, dsh_cache):
        oc = _agg(oc_tailers.values())
        if dsh_parser.HAS_ZSTD:
            dsh = _agg(st for (_m, _s, st) in dsh_cache.values())
        else:
            dsh = (STATE_DISCONNECTED, 0, 0, 0, 0)
        overall = self._overall(oc[0], dsh[0])
        return overall, oc, dsh

    def _overall(self, oc_state, dsh_state):
        best = STATE_DISCONNECTED
        for s in (oc_state, dsh_state):
            if _PRIORITY[s] > _PRIORITY[best]:
                best = s
        return best

    def _payload(self, oc_tailers, dsh_cache, sig) -> dict:
        overall, oc, dsh = sig

        oc_sessions = self._sort_sessions(self._oc_sessions(oc_tailers))
        dsh_sessions = self._sort_sessions(self._dsh_sessions(dsh_cache))
        all_sessions = self._sort_sessions(oc_sessions + dsh_sessions)

        sources = {
            "opencode": self._source_payload(
                oc,
                bool(self._oc_dir) and os.path.isdir(self._oc_dir),
                sessions=oc_sessions,
            ),
            "dsh": self._source_payload(
                dsh,
                bool(self._dsh_dir) and os.path.isdir(self._dsh_dir),
                None if dsh_parser.HAS_ZSTD else "缺少 zstandard 库（pip install zstandard）",
                sessions=dsh_sessions,
            ),
        }
        return {
            "state": overall,
            "active": oc[1] + dsh[1],
            "busy": oc[2] + dsh[2],
            "questions": oc[3] + dsh[3],
            "permissions": oc[4] + dsh[4],
            "sources": sources,
            "sessions": all_sessions,
        }
