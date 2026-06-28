import os
import asyncio
import time
import json
import websockets
from telegram import Bot
from flask import Flask
import threading
from collections import deque

# ================= DUMMY WEB SERVER =================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "iTick WebSocket Scanner is running.", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_web, daemon=True).start()
# ====================================================

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ITICK_TOKEN = os.getenv("ITICK_TOKEN")

if not TOKEN or not CHAT_ID or not ITICK_TOKEN:
    raise ValueError("Missing TELEGRAM_TOKEN, CHAT_ID, or ITICK_TOKEN")

bot = Bot(token=TOKEN)

# ================= SETTINGS =================
MIN_VOLUME = 100000  # الحد الأدنى للحجم
MIN_MOMENTUM = 2.0   # الحد الأدنى للزخم (%)
MIN_ACCELERATION = 0.5  # الحد الأدنى للتسارع (%)
MIN_VOLUME_SPIKE = 2.0  # الحد الأدنى لارتفاع الحجم النسبي (x)

# ================= FIXED SYMBOLS LIST (500) =================
SYMBOLS = [
    "TRUG", "SHPH", "DGLY", "MSCF", "SFCX", "IMAQ", "CIWV", "CBWA", "WBBW", "KEFI",
    "HFBK", "FRSB", "AABB", "CBAF", "ORBN", "GCCO", "GWIN", "WEEEF", "SYZLF", "TMLL",
    "LVPR", "MVLY", "JANL", "WBSR", "LFGP", "VSQTF", "MLGF", "LICT", "NTPIF", "FRMO",
    "FGPR", "RVRF", "SGLA", "CRSF", "CNND", "EACO", "EXCO", "GRIQ", "BWEL", "AONC",
    "MDRX", "MCCK", "RWWI", "PHCI", "MUEL", "RCB", "TTLOF", "PHIG", "SWRD", "BCOM",
    "WTBFA", "SVM", "CMF", "SSRGBF", "BBOTY",
    "ARMP", "SKYX", "OTGA", "MBI", "JENA", "GSRF", "HVMC", "JMSB", "EGHT", "IONR",
    "NUCL", "ELDN", "IRHO", "VFF", "CAII", "CAN", "ONIT", "GPAC", "IKT", "HCAC",
    "PONO", "SVAQ", "BRBS", "OPTU", "BACC", "PACH", "XPOF", "ZNTL", "KPET", "NUS",
    "FJET", "MTNE", "KWY", "FATE", "AACB", "NCMI", "NODK", "RCKY", "BRT", "HRZN",
    "UCFI", "ADAC", "LPCV", "HCKT", "FGII", "ACGC", "FLWS", "UIS", "DSX", "LEGT",
    "OSUR", "GTE", "ACIU", "FVCB", "AIFU", "FCCO", "AXIN", "IACQ", "FNRN", "TVAI",
    "STEX", "XCBE", "SBXD", "AKBA", "PAII", "ARQQ", "LPRO", "GUAC", "MYFW", "ADAG",
    "TG", "MKTW", "CNDT", "ACRE", "XNET", "LPTH", "NEWP", "FEIM", "APPS", "ASYS",
    "ALMU", "PGY", "MTC", "BKTI", "OSS", "CSIQ", "GILT", "FORTY", "SHMD", "MGRT",
    "TROO", "PRCH", "EVLV", "IBEX", "DUOT", "BKSY", "BTQ", "PAYS", "ADUR", "SHAZ",
    "SCZM", "TOI", "RLMD", "XMAX", "XWIN", "PVLA", "ASM", "MCTA", "NEGG", "DBVT",
    "NNNN", "USAS", "IVVD", "INBX", "NUTX", "GLTO", "DMRA", "ITRG", "TDUP", "SUPX",
    "SIFY", "OLMA", "CTMX", "ANRO", "BHVN", "GLSI", "HSTM", "IMMX", "IRMD", "IMOS",
    "LCID", "INVX", "GTY", "NGL", "PRKS", "STC", "NEOG", "LC", "WMK", "AGM",
    "HCI", "AIN", "GRND", "OFG", "NVCR", "FCF", "BXDC", "NTST", "FIGS", "EZPW",
    "XPRO", "SOXQ", "TRVI", "STEL", "NKTR", "BHC", "PEB", "OMCL", "PLGO", "JPEF",
    "CMRE", "GEL", "HCM", "SLDE", "SPB", "POET", "NTLA", "HMN", "NBHC", "TIC",
    "TGLS", "NUV", "WB", "HRMY", "SKWD", "ZLAB", "ECO", "ADMA", "INTA", "CTS",
    "MLYS", "KOD", "LPG", "MD", "TY", "KSS", "PSNY"
]

# ================= CACHE =================
PRICE_CACHE = {}
VOLUME_CACHE = {}
LAST_ALERT = {}
DAILY_ALERTS = {}

# ================= TELEGRAM =================
async def send(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    except Exception as e:
        print(f"[Telegram Error] {e}")

# ================= SIGNAL SCORE =================
def get_signal_score(momentum, acceleration, volume_spike):
    score = 0
    # الزخم
    if momentum >= 5: score += 35
    elif momentum >= 3: score += 25
    elif momentum >= 2: score += 15
    
    # التسارع
    if acceleration >= 1.5: score += 30
    elif acceleration >= 1.0: score += 20
    elif acceleration >= 0.5: score += 10
    
    # الحجم النسبي
    if volume_spike >= 4.0: score += 35
    elif volume_spike >= 3.0: score += 25
    elif volume_spike >= 2.0: score += 15
    
    return min(score, 100)

# ================= CAN ALERT =================
def can_alert(symbol):
    now = time.time()
    if symbol in LAST_ALERT:
        if now - LAST_ALERT[symbol] < 300:
            return False
    LAST_ALERT[symbol] = now
    return True

# ================= DETECT SUDDEN SURGE =================
def detect_surge(symbol, price, volume):
    now = time.time()
    
    # تهيئة الكاش
    if symbol not in PRICE_CACHE:
        PRICE_CACHE[symbol] = {"previous": price, "current": price, "time": now}
        VOLUME_CACHE[symbol] = deque(maxlen=10)
        VOLUME_CACHE[symbol].append(volume)
        return False
    
    # تحديث الأسعار
    previous_price = PRICE_CACHE[symbol]["current"]
    PRICE_CACHE[symbol]["previous"] = previous_price
    PRICE_CACHE[symbol]["current"] = price
    PRICE_CACHE[symbol]["time"] = now
    
    # تحديث الحجم
    VOLUME_CACHE[symbol].append(volume)
    
    # حساب الزخم (Momentum)
    if previous_price <= 0:
        return False
    momentum = ((price - previous_price) / previous_price) * 100
    
    # حساب التسارع (Acceleration)
    acceleration = 0
    if len(PRICE_CACHE[symbol]) > 2:
        # محاكاة للتسارع (فرق بين آخر تغيرين)
        acceleration = momentum * 0.3  # تبسيط
    
    # حساب الحجم النسبي (Relative Volume)
    volume_spike = 1.0
    if len(VOLUME_CACHE[symbol]) >= 5:
        avg_volume = sum(list(VOLUME_CACHE[symbol])[-5:]) / 5
        volume_spike = volume / avg_volume if avg_volume > 0 else 1.0
    
    # شروط الاندفاع المفاجئ
    is_surge = (
        momentum >= MIN_MOMENTUM and
        acceleration >= MIN_ACCELERATION and
        volume_spike >= MIN_VOLUME_SPIKE and
        volume >= MIN_VOLUME
    )
    
    if is_surge:
        return {
            "momentum": momentum,
            "acceleration": acceleration,
            "volume_spike": volume_spike,
            "volume": volume,
            "price": price
        }
    
    return False

# ================= WEBSOCKET HANDLER =================
async def itick_websocket():
    symbols_param = ",".join([f"{sym}$US" for sym in SYMBOLS[:500]])
    
    uri = "wss://api.itick.org/stock"
    headers = {"token": ITICK_TOKEN}
    
    try:
        async with websockets.connect(uri, extra_headers=headers) as websocket:
            print("✅ متصل بـ iTick WebSocket")
            await send("✅ *متصل بـ iTick WebSocket - استراتيجية الاندفاع المفاجئ*")
            
            subscribe_msg = {
                "ac": "subscribe",
                "params": symbols_param,
                "types": "quote,tick"
            }
            await websocket.send(json.dumps(subscribe_msg))
            print(f"📡 تم الاشتراك في {len(SYMBOLS)} سهماً")
            
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await process_websocket_data(data)
                except Exception as e:
                    print(f"خطأ في المعالجة: {e}")
                    
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        await asyncio.sleep(5)

# ================= PROCESS WEBSOCKET DATA =================
async def process_websocket_data(data):
    symbol = data.get("symbol")
    price = data.get("price") or data.get("ld")
    volume = data.get("volume") or data.get("v")
    
    if not symbol or not price:
        return
    
    # كشف الاندفاع
    surge_data = detect_surge(symbol, price, volume)
    
    if surge_data and can_alert(symbol):
        momentum = surge_data["momentum"]
        acceleration = surge_data["acceleration"]
        volume_spike = surge_data["volume_spike"]
        current_price = surge_data["price"]
        
        score = get_signal_score(momentum, acceleration, volume_spike)
        
        today = time.strftime("%Y-%m-%d")
        if today not in DAILY_ALERTS:
            DAILY_ALERTS[today] = {}
        DAILY_ALERTS[today][symbol] = DAILY_ALERTS[today].get(symbol, 0) + 1
        
        msg = (
            f"🚨 *اندفاع مفاجئ* 🚨\n\n"
            f"📊 الرمز: `{symbol}`\n"
            f"💰 السعر: `${current_price:.2f}`\n"
            f"📈 الزخم: `+{momentum:.2f}%`\n"
            f"🚀 التسارع: `+{acceleration:.2f}%`\n"
            f"📊 الحجم النسبي: `{volume_spike:.1f}x`\n"
            f"🔥 القوة: `{score}/100`\n"
            f"🔢 التنبيه: `{DAILY_ALERTS[today][symbol]}`\n"
            f"🕒 {time.strftime('%H:%M:%S')}\n\n"
            f"⚠️ للمتابعة فقط"
        )
        
        await send(msg)
        print(f"📤 تم إرسال تنبيه لـ {symbol}")

# ================= MAIN =================
async def main():
    await send("🔥 *الماسح الفوري - استراتيجية الاندفاع المفاجئ*")
    print("🚀 بدء تشغيل WebSocket...")
    
    while True:
        try:
            await itick_websocket()
        except Exception as e:
            print(f"🔄 إعادة الاتصال: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
