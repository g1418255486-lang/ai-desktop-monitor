"""额度查询服务：智谱 / Z.ai API 客户端与后台 Worker。

百分比与重置时间均来自 /api/monitor/usage/quota/limit：
TOKENS_LIMIT(unit=3) = 5 小时窗口，(unit=6) = 每周窗口。
"""

import requests
from typing import Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from PySide6.QtCore import QObject, Signal


PLATFORMS = {
    "zhipu": {
        "name": "智谱 (open.bigmodel.cn)",
        "base_url": "https://open.bigmodel.cn",
    },
    "zai": {
        "name": "Z.ai (api.z.ai)",
        "base_url": "https://api.z.ai",
    },
}


class UsageData:
    """仅保留 UI 实际消费的字段。"""

    def __init__(self):
        self.token_5h_pct: Optional[float] = None
        self.token_weekly_pct: Optional[float] = None
        self.token_5h_reset: Optional[int] = None
        self.token_weekly_reset: Optional[int] = None
        self.error: Optional[str] = None


class APIClient:
    def __init__(self, api_key: str, platform_key: str = "zhipu"):
        self.api_key = api_key
        self.platform_key = platform_key
        self.platform_info = PLATFORMS.get(platform_key, PLATFORMS["zhipu"])
        self.base_url = self.platform_info["base_url"]

        self.session = requests.Session()
        retry = Retry(total=2, backoff_factor=1,
                      status_forcelist=[429, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass

    def _get_headers(self):
        return {
            "Authorization": self.api_key,
            "Accept-Language": "zh-CN,zh",
            "Content-Type": "application/json",
        }

    def _query(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        resp = self.session.get(url, headers=self._get_headers(), params=params, timeout=10)
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def fetch_all(self) -> UsageData:
        data = UsageData()
        try:
            raw = self._query("/api/monitor/usage/quota/limit")
            quota = raw.get("data", raw)
            for item in (quota or {}).get("limits", []):
                if item.get("type") != "TOKENS_LIMIT":
                    continue
                unit = item.get("unit")
                pct = item.get("percentage")
                reset_ts = item.get("nextResetTime")
                if unit == 3:
                    data.token_5h_pct = pct
                    data.token_5h_reset = reset_ts
                elif unit == 6:
                    data.token_weekly_pct = pct
                    data.token_weekly_reset = reset_ts
        except Exception as e:
            data.error = f"配额查询失败: {e}"
        return data


class QuotaWorker(QObject):
    """在 QThread 中执行一次额度查询，完成后发出 finished(object)。"""

    finished = Signal(object)

    def __init__(self, api_key: str, platform: str):
        super().__init__()
        self.api_key = api_key
        self.platform = platform

    def run(self):
        client = None
        try:
            client = APIClient(self.api_key, self.platform)
            data = client.fetch_all()
            self.finished.emit(data)
        except Exception as e:
            d = UsageData()
            d.error = str(e)
            self.finished.emit(d)
        finally:
            if client:
                client.close()
