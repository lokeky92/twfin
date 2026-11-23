"""
共用工具：台灣時區時間、具重試／退避／限速的官方 API JSON 擷取器。

所有後端模組應由此取得「現在時間」，避免在 UTC 主機 (GitHub Actions / Render / Docker)
上以 datetime.now() 加上 "+08:00" 字尾，造成時間戳整整差 8 小時。
"""
import json
import logging
import ssl
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

TW_TZ = timezone(timedelta(hours=8))

logger = logging.getLogger("twfin")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def now_tw():
    """目前的台灣時間 (aware datetime, UTC+8)。"""
    return datetime.now(TW_TZ)


def now_iso():
    """台灣時間 ISO 字串，例如 2026-11-23T20:00:00+08:00。"""
    return now_tw().strftime("%Y-%m-%dT%H:%M:%S+08:00")


# ---------------------------------------------------------------------------
# HTTP 擷取：每個主機的最小請求間隔 + 指數退避重試
# ---------------------------------------------------------------------------
_SSL_CTX = ssl.create_default_context()
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TWFin-Research-Engine/1.0"

# 證交所 www.twse.com.tw 的 RWD JSON 端點官方建議每 3 秒最多 1 次，過快會被暫時封鎖 IP
HOST_MIN_INTERVAL_SEC = {
    "www.twse.com.tw": 3.0,
}
DEFAULT_MIN_INTERVAL_SEC = 0.5

_rate_lock = threading.Lock()
_last_request_at = {}


def _respect_rate_limit(host):
    interval = HOST_MIN_INTERVAL_SEC.get(host, DEFAULT_MIN_INTERVAL_SEC)
    with _rate_lock:
        last = _last_request_at.get(host)
        now = time.monotonic()
        if last is not None and now - last < interval:
            time.sleep(interval - (now - last))
        _last_request_at[host] = time.monotonic()


def _is_retryable(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or exc.code >= 500
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError))


def fetch_json(url, timeout=15, retries=3, backoff_sec=2.0):
    """
    取得 JSON。對網路錯誤、逾時、HTTP 429/5xx 與非 JSON 回應 (常見於被限流時回傳 HTML) 進行指數退避重試；
    4xx (429 以外) 直接拋出，不浪費時間重試。
    """
    host = urlparse(url).netloc
    last_exc = None
    for attempt in range(max(1, retries)):
        _respect_rate_limit(host)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — 由 _is_retryable 判斷
            last_exc = exc
            if not _is_retryable(exc) or attempt == retries - 1:
                break
            wait = backoff_sec * (2 ** attempt)
            logger.warning("fetch_json 失敗 (%s: %s)，%.1f 秒後重試 %d/%d：%s",
                           type(exc).__name__, exc, wait, attempt + 1, retries - 1, url)
            time.sleep(wait)
    raise last_exc
