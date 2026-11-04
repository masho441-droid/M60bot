import logging
import pandas as pd
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

class MarketDataError(Exception):
    pass

def get_daily_bars(limit: int = 60) -> List[Dict[str, Any]]:
    """جلب بيانات SPX اليومية من Stooq (بديل مستقر لياهو)"""
    try:
        # stooq يستخدم الرمز ^spx لمؤشر S&P 500
        url = "https://stooq.com/q/d/l/?s=^spx&i=d"
        df = pd.read_csv(url)
        
        if df.empty:
            raise MarketDataError("No data returned from Stooq")
        
        df.columns = [c.lower() for c in df.columns]
        # نحتفظ بآخر limit شمعة
        df = df.tail(limit)
        
        bars = []
        for _, row in df.iterrows():
            bars.append({
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "c": float(row["close"]),
                "v": 0.0 # stooq لا يوفر الحجم للمؤشرات في هذا الرابط، لا نحتاجه للتقرير
            })
        
        return bars
    except Exception as e:
        logger.error(f"Stooq fetch error: {e}")
        raise MarketDataError(str(e))

def get_previous_close() -> float:
    bars = get_daily_bars(limit=3)
    return float(bars[-1]["c"])
