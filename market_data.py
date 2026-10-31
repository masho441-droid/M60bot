import logging
from datetime import datetime
from typing import Any, Dict, List
import yfinance as yf

logger = logging.getLogger(__name__)

class MarketDataError(Exception):
    pass

def get_daily_bars(limit: int = 60) -> List[Dict[str, Any]]:
    """جلب بيانات SPX اليومية من yfinance (مجاني وبدون مفتاح)"""
    try:
        # نستخدم ^GSPC لجلب مؤشر S&P 500
        df = yf.download("^GSPC", period="3mo", interval="1d", progress=False)
        if df.empty:
            raise MarketDataError("No data returned from yfinance")
        
        # تنظيف البيانات وتحويلها للتنسيق المطلوب
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df.columns = [c.lower() for c in df.columns]
        
        results = []
        for index, row in df.iterrows():
            results.append({
                "t": int(index.timestamp() * 1000),
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "c": float(row["close"]),
                "v": float(row["volume"])
            })
        
        # نأخذ آخر limit شمعة فقط
        return results[-limit:]
    except Exception as e:
        logger.error(f"yfinance fetch error: {e}")
        raise MarketDataError(str(e))

def get_previous_close() -> float:
    bars = get_daily_bars(limit=3)
    return float(bars[-1]["c"])
