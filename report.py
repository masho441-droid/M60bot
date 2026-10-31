from datetime import datetime
from typing import Any, Dict

def build_report(pivot: Dict[str, float], trend: Dict[str, Any], atr: float, prev_close: float) -> str:
    change = pivot["close"] - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0.0
    now_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    html = (
        f"📊 <b>تقرير SPX الصباحي — {datetime.utcnow().date()}</b>\n\n"
        f"💵 <b>إغلاق سابق:</b> {pivot['close']:.2f} "
        f"({'▲' if change >= 0 else '▼'} {change:+.2f} / {change_pct:+.2f}%)\n\n"
        f"⚪ <b>نقطة الارتكاز (Pivot):</b> {pivot['pivot']:.2f}\n\n"
        f"🔴 <b>مقاومات:</b>\n"
        f"  R1: {pivot['r1']:.2f}\n  R2: {pivot['r2']:.2f}\n  R3: {pivot['r3']:.2f}\n\n"
        f"🟢 <b>دعوم:</b>\n"
        f"  S1: {pivot['s1']:.2f}\n  S2: {pivot['s2']:.2f}\n  S3: {pivot['s3']:.2f}\n\n"
        f"📈 <b>الاتجاه العام:</b> {trend['trend']}\n<i>{trend['reason']}</i>\n\n"
        f"🎯 <b>مستويات المراقبة:</b>\n"
        f"  • اختراق {pivot['r1']:.2f} → يستهدف {pivot['r2']:.2f}\n"
        f"  • كسر {pivot['s1']:.2f} → يستهدف {pivot['s2']:.2f}\n\n"
        f"📉 <b>ATR (تقلب يومي):</b> {atr:.2f}\n\n"
        f"⏰ {now_utc} | البيانات من Polygon.io"
    )
    return html
