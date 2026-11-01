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
        
        bars = []
        for i in range(len(timestamps)):
            if closes[i] is not None:
                bars.append({"c": float(closes[i])})
        return bars[-limit:]
    except Exception as e:
        logger.error(f"Error fetching daily bars: {e}")
        return []

def calculate_pivot_levels(bars: List[Dict]) -> Dict[str, float]:
    if len(bars) < 2:
        return {}
    
    # نستخدم آخر شمعة مكتملة (أمس)
    prev_bar = bars[-2] # ملاحظة: ياهو يعطي إغلاق اليوم الحالي، لذا نأخذ ما قبل الأخير
    H = prev_bar.get("h", prev_bar["c"])
    L = prev_bar.get("l", prev_bar["c"])
    C = prev_bar["c"]
    
    P = (H + L + C) / 3
    R1 = 2 * P - L
    S1 = 2 * P - H
    
    # حساب المستويات الوسيطة (Mid-Levels)
    levels = {
        "R1": round(R1, 2),
        "Pivot": round(P, 2),
        "S1": round(S1, 2),
        "R1.5": round((P + R1) / 2, 2),
        "P.5": round((P + S1) / 2, 2),
        "S1.5": round((S1 - 20), 2), # مستوى إضافي أسفل S1
        "R2": round(R1 + 25, 2),     # مستوى إضافي أعلى R1
    }
    return levels
