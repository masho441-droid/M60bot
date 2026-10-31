import logging
from typing import Any, Dict, List
import pandas as pd
import requests
from io import StringIO

logger = logging.getLogger(__name__)

class MarketDataError(Exception):
    pass

def get_daily_bars(limit: int = 60) -> List[Dict[str, Any]]:
    """جلب بيانات SPX اليومية من Stooq (مجاني ولا يحظر السيرفرات)"""
    try:
        url = "https://stooq.com/q/d/l/?s=^spx&i=d"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        
        df = pd.read_csv(StringIO(response.text))
        if df.empty:
            raise MarketDataError("No data from Stooq")
        
        df.columns = [c.lower() for c in df.columns]
        df = df.tail(limit)
        
        results = []
        for _, row in df.iterrows():
            results.append({
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "c": float(row["close"]),
                "v": float(row["volume"]) if "volume" in row else 0
            })
        return results
    except Exception as e:
        logger.error(f"Stooq fetch error: {e}")
        raise MarketDataError(str(e))

def get_previous_close() -> float:
    """إغلاق اليوم السابق (مطلوب لملف bot.py)"""
    bars = get_daily_bars(limit=3)
    return float(bars[-1]["c"])
