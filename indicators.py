from typing import Any, Dict, List

def calculate_pivot(bars: List[Dict[str, Any]]) -> Dict[str, float]:
    last = bars[-1]
    H = float(last["h"])
    L = float(last["l"])
    C = float(last["c"])
    P = (H + L + C) / 3
    R1 = 2 * P - L
    S1 = 2 * P - H
    R2 = P + (H - L)
    S2 = P - (H - L)
    R3 = H + 2 * (P - L)
    S3 = L - 2 * (H - P)
    return {
        "pivot": round(P, 2),
        "r1": round(R1, 2), "r2": round(R2, 2), "r3": round(R3, 2),
        "s1": round(S1, 2), "s2": round(S2, 2), "s3": round(S3, 2),
        "high": round(H, 2), "low": round(L, 2), "close": round(C, 2),
    }

def _ema(values: List[float], period: int) -> List[float]:
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema

def _rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_trend(bars: List[Dict[str, Any]]) -> Dict[str, Any]:
    closes = [float(b["c"]) for b in bars]
    if len(closes) < 50:
        return {"trend": "NEUTRAL", "reason": "Insufficient data", "ema20": 0, "ema50": 0, "rsi": 50, "macd": 0}

    ema20 = _ema(closes, 20)[-1]
    ema50 = _ema(closes, 50)[-1]
    rsi = _rsi(closes)
    last_close = closes[-1]
    ema12 = _ema(closes, 12)[-1]
    ema26 = _ema(closes, 26)[-1]
    macd = ema12 - ema26

    if last_close > ema20 and last_close > ema50 and rsi > 55 and macd > 0:
        trend, reason = "صاعد", "السعر فوق EMA20/EMA50، RSI>55، MACD إيجابي"
    elif last_close < ema20 and last_close < ema50 and rsi < 45 and macd < 0:
        trend, reason = "هابط", "السعر تحت EMA20/EMA50، RSI<45، MACD سلبي"
    else:
        trend, reason = "محايد", "إشارات متضاربة"

    return {
        "trend": trend, "reason": reason,
        "ema20": round(ema20, 2), "ema50": round(ema50, 2),
        "rsi": round(rsi, 2), "macd": round(macd, 2),
    }

def calculate_atr(bars: List[Dict[str, Any]], period: int = 14) -> float:
    trs = []
    for i in range(1, len(bars)):
        h = float(bars[i]["h"])
        l = float(bars[i]["l"])
        prev_c = float(bars[i - 1]["c"])
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    if len(trs) < period:
        return 0.0
    return round(sum(trs[-period:]) / period, 2)
