import time
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import httpx
from config import POLYGON_API_KEY

logger = logging.getLogger(__name__)

BASE_URL = "https://api.polygon.io"
CACHE_TTL_SECONDS = 300
_cache: Dict[str, Any] = {}
_cache_times: Dict[str, float] = {}

class MarketDataError(Exception):
    pass

def _cache_get(key: str) -> Optional[Any]:
    if key in _cache and (time.time() - _cache_times.get(key, 0)) < CACHE_TTL_SECONDS:
        return _cache[key]
    return None

def _cache_set(key: str, value: Any) -> None:
    _cache[key] = value
    _cache_times[key] = time.time()

def _fetch_with_retry(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    delay = 1.0
    for attempt in range(3):
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=resp.request, response=resp)
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning("Fetch failed (attempt %d): %s", attempt + 1, exc)
            if attempt < 2:
                time.sleep(delay)
                delay *= 2
            else:
                raise MarketDataError(str(exc)) from exc
    raise MarketDataError("Unreachable")

def get_daily_bars(limit: int = 60) -> List[Dict[str, Any]]:
    cache_key = f"daily_{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    end = datetime.utcnow().date()
    start = end - timedelta(days=limit * 2)
    url = f"{BASE_URL}/v2/aggs/ticker/I:SPX/range/1/day/{start}/{end}"
    params = {"apiKey": POLYGON_API_KEY, "limit": limit, "sort": "asc"}
    data = _fetch_with_retry(url, params)
    results = data.get("results", [])
    if not results:
        raise MarketDataError("No daily bars returned")
    _cache_set(cache_key, results)
    return results

def get_previous_close() -> float:
    bars = get_daily_bars(limit=3)
    return float(bars[-1]["c"])
