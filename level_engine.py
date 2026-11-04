import logging
import requests
import yfinance as yf
from typing import Dict, List

logger = logging.getLogger(__name__)

def get_daily_bars(limit: int = 60) -> List[Dict]:
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/^GSPC"
        headers = {"User-Agent": "Mozilla/5.0"}
        params = {"range": "3mo", "interval": "1d"}
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return []
        chart = result[0]
        timestamps = chart.get("timestamp", [])
        indicators = chart.get("indicators", {}).get("quote", [{}])[0]
        closes = indicators.get("close", [])
        highs = indicators.get("high", [])
        lows = indicators.get("low", [])
        opens = indicators.get("open", [])
        
        bars = []
        for i in range(len(timestamps)):
            if closes[i] is not None and highs[i] is not None and lows[i] is not None:
                bars.append({
                    "t": timestamps[i],
                    "o": float(opens[i]) if opens[i] is not None else float(closes[i]),
                    "h": float(highs[i]),
                    "l": float(lows[i]),
                    "c": float(closes[i])
                })
        return bars[-limit:]
    except Exception as e:
        logger.error(f"Error fetching daily bars: {e}")
        return []

def calculate_pivot_levels(bars: List[Dict]) -> Dict[str, float]:
    if len(bars) < 2:
        return {}
    
    prev_bar = bars[-2] if len(bars) >= 2 else bars[-1]
    H = prev_bar["h"]
    L = prev_bar["l"]
    C = prev_bar["c"]
    
    P = (H + L + C) / 3
    R1 = 2 * P - L
    S1 = 2 * P - H
    R2 = P + (H - L)
    S2 = P - (H - L)
    
    levels = {
        "R2": round(R2, 2),
        "R1": round(R1, 2),
        "Pivot": round(P, 2),
        "S1": round(S1, 2),
        "S2": round(S2, 2),
        "R1.5": round((P + R1) / 2, 2),
        "S1.5": round((P + S1) / 2, 2),
    }
    return levels
