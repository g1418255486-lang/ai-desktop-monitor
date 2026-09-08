"""单文件日志尾随与解析。

移植自 OpenCodeMonitor/Services/LogFileWatcher.cs：
- 非阻塞轮询新增字节（Windows 下 open() 默认共享读写，opencode 可继续写入）
- 初始化时先读末尾 TAIL_INIT_BYTES 字节恢复状态
- 同时兼容 opencode 新旧两种日志格式
"""

import os

TAIL_INIT_BYTES = 50000


class LogTailer:
    def __init__(self, path: str):
        self.path = path
        self.is_busy = False
        self.pending_questions = 0
        self.pending_permissions = 0
        self._f = None
        self._pos = 0
        self._rest = b""
        self._open(init=True)

    # ─── 文件管理 ───

    def _open(self, init: bool):
        """打开文件并读取（init 时从末尾 50KB 起，轮转后从头起）。"""
        self._f = open(self.path, "rb")
        size = os.fstat(self._f.fileno()).st_size
        if init:
            self._f.seek(max(0, size - TAIL_INIT_BYTES))
        else:
            self._f.seek(0)
        self._rest = b""
        data = self._f.read()
        self._pos = self._f.tell()
        self._feed(data)

    def poll(self) -> bool:
        """非阻塞读取新增字节，返回状态是否发生变化。"""
        if self._f is None:
            try:
                self._open(init=True)
                return True
            except OSError:
                return False
        try:
            size = os.fstat(self._f.fileno()).st_size
            if size < self._pos:
                # 文件被截断/轮转：重新打开恢复
                self._f.close()
                self._open(init=True)
                return True
            if size > self._pos:
                self._f.seek(self._pos)
                data = self._f.read()
                self._pos = self._f.tell()
                return self._feed(data)
        except OSError:
            try:
                if self._f:
                    self._f.close()
            except Exception:
                pass
            self._f = None
        return False

    def close(self):
        try:
            if self._f:
                self._f.close()
        except Exception:
            pass
        self._f = None

    # ─── 行处理 ───

    def _feed(self, data: bytes) -> bool:
        changed = False
        data = self._rest + data
        lines = data.split(b"\n")
        self._rest = lines.pop()  # 末尾不完整行留待下次
        for raw in lines:
            line = raw.decode("utf-8", "replace").rstrip("\r")
            if line:
                changed = self._process_line(line) or changed
        return changed

    def _process_line(self, line: str) -> bool:
        """逐条移植 C# ProcessLine 的解析规则。"""
        changed = False

        # 会话空闲：全部清零
        if ("exiting loop" in line
                or "message=cancel" in line
                or "type=session.idle publishing" in line):
            if self.is_busy:
                self.is_busy = False
                changed = True
            if self.pending_questions > 0:
                self.pending_questions = 0
                changed = True
            if self.pending_permissions > 0:
                self.pending_permissions = 0
                changed = True

        # Agent 循环进行中
        if "step=" in line and "loop" in line:
            if not self.is_busy:
                self.is_busy = True
                changed = True
            if "step=0" in line and (self.pending_questions > 0 or self.pending_permissions > 0):
                self.pending_questions = 0
                self.pending_permissions = 0
                changed = True
            elif self.pending_permissions > 0:
                self.pending_permissions = 0
                changed = True

        # 提问出现
        if (("message=asking" in line and "que_" in line)
                or "type=question.asked publishing" in line):
            self.pending_questions += 1
            changed = True

        # 权限请求出现
        if (("message=asking" in line and "per_" in line)
                or "type=permission.asked publishing" in line):
            self.pending_permissions += 1
            changed = True

        # 回复
        if "message=replied" in line:
            if "per_" in line:
                self.pending_permissions = max(0, self.pending_permissions - 1)
            else:
                self.pending_questions = max(0, self.pending_questions - 1)
            changed = True
        elif ("type=question.replied publishing" in line
                or "type=question.rejected publishing" in line):
            self.pending_questions = max(0, self.pending_questions - 1)
            changed = True
        elif "type=permission.replied publishing" in line:
            self.pending_permissions = max(0, self.pending_permissions - 1)
            changed = True

        # external_directory 权限自动解决
        if ("message=evaluated" in line
                and "external_directory" in line
                and self.pending_permissions > 0):
            self.pending_permissions = 0
            changed = True

        return changed
