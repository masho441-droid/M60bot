import logging
from typing import Any, Dict, List
import requests
import os

logger = logging.getLogger(__name__)

class MarketDataError(Exception):
    pass

def get_daily_bars(limit: int = 60) -> List[Dict[str, Any]]:
    """جلب بيانات SPX اليومية من Yahoo Finance مباشرة (بدون مكتبة معقدة)"""
    try:
        # نستخدم Yahoo Finance Query API مباشرة مع User-Agent لتجنب الحظر
        url = "https://query1.finance.yahoo.com/v8/finance/chart/^GSPC"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        params = {
            "range": "3mo",
            "interval": "1d"
        }
        
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        result = data.get("chart", {}).get("result", [])
        if not result:
            raise MarketDataError("No data from Yahoo Finance")
            
        chart = result[0]
        timestamps = chart.get("timestamp", [])
        indicators = chart.get("indicators", {}).get("quote", [{}])[0]
        
        opens = indicators.get("open", [])
        highs = indicators.get("high", [])
        lows = indicators.get("low", [])
        closes = indicators.get("close", [])
        volumes = indicators.get("volume", [])
        
        bars = []
        for i in range(len(timestamps)):
            if closes[i] is None:
                continue
            bars.append({
                "o": float(opens[i]),
                "h": float(highs[i]),
                "l": float(lows[i]),
                "c": float(closes[i]),
                "v": float(volumes[i]) if volumes[i] else 0.0
            })
            
        if len(bars) < 3:
            raise MarketDataError("Insufficient data from Yahoo Finance")
            
        return bars[-limit:]
        
    except Exception as e:
        logger.error(f"Yahoo Finance fetch error: {e}")
        raise MarketDataError(str(e))

def get_previous_close() -> float:
    bars = get_daily_bars(limit=3)
    return float(bars[-1]["c"])
