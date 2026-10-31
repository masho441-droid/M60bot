from datetime import datetime
from typing import Any, Dict

def build_report(pivot: Dict[str, float], trend: Dict[str, Any], atr: float, prev_close: float) -> str:
    change = pivot["close"] - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0.0
    now_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    text = (
        f"📊 تقرير SPX الصباحي — {datetime.utcnow().date()}\n\n"
        f"💵 إغلاق سابق: {pivot['close']:.2f} "
        f"({'▲' if change >= 0 else '▼'} {change:+.2f} / {change_pct:+.2f}%)\n\n"
        f"⚪ نقطة الارتكاز (Pivot): {pivot['pivot']:.2f}\n\n"
        f"🔴 مقاومات:\n"
        f"  R1: {pivot['r1']:.2f}\n  R2: {pivot['r2']:.2f}\n  R3: {pivot['r3']:.2f}\n\n"
        f"🟢 دعوم:\n"
        f"  S1: {pivot['s1']:.2f}\n  S2: {pivot['s2']:.2f}\n  S3: {pivot['s3']:.2f}\n\n"
        f"📈 الاتجاه العام: {trend['trend']}\n"
        f"{trend['reason']}\n\n"
        f"🎯 مستويات المراقبة:\n"
        f"  • اختراق {pivot['r1']:.2f} → يستهدف {pivot['r2']:.2f}\n"
        f"  • كسر {pivot['s1']:.2f} → يستهدف {pivot['s2']:.2f}\n\n"
        f"📉 ATR (تقلب يومي): {atr:.2f}\n\n"
        f"⏰ {now_utc} | البيانات من Yahoo Finance"
    )
    return text
