import os
import asyncio
import time
import json
import requests
import websockets
from telegram import Bot
from flask import Flask
import threading

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
MIN_PRICE = 0.5
MAX_PRICE = 10
MIN_VOLUME = 100000
TOP_SYMBOLS = 500

# ================= CACHE =================
PRICE_CACHE = {}
LAST_ALERT = {}
DAILY_ALERTS = {}
HOT_SYMBOLS = []

# ================= TELEGRAM =================
async def send(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    except Exception as e:
        print(f"[Telegram Error] {e}")

# ================= SIGNAL SCORE =================
def get_signal_score(change):
    if change >= 5: return 85
    elif change >= 3: return 70
    elif change >= 1: return 60
    elif change >= 0.5: return 50
    return 40

# ================= CAN ALERT =================
def can_alert(symbol):
    now = time.time()
    if symbol in LAST_ALERT:
        if now - LAST_ALERT[symbol] < 300:
            return False
    LAST_ALERT[symbol] = now
    return True

# ================= DETECT MOMENTUM =================
def detect(symbol, price):
    if symbol not in PRICE_CACHE:
        PRICE_CACHE[symbol] = {"previous": price, "current": price}
        return False

    previous = PRICE_CACHE[symbol]["current"]
    PRICE_CACHE[symbol]["previous"] = previous
    PRICE_CACHE[symbol]["current"] = price

    if previous <= 0:
        return False

    change = ((price - previous) / previous) * 100
    return change >= 0.12

# ================= FETCH TOP SYMBOLS (REST) =================
def fetch_top_symbols():
    """جلب أعلى 500 سهم نشاطاً"""
    try:
        # 1. جلب قائمة جميع الأسهم
        url = "https://api.itick.org/symbol/list"
        headers = {"accept": "application/json", "token": ITICK_TOKEN}
        params = {"type": "stock", "region": "US", "limit": 1000}
        r = requests.get(url, headers=headers, params=params, timeout=15)
        
        if r.status_code != 200:
            print(f"REST error: {r.status_code}")
            return []
        
        data = r.json()
        symbols = []
        for item in data.get("data", []):
            symbol = item.get("symbol") or item.get("code")
            if symbol:
                symbols.append(symbol)
        
        # 2. جلب بيانات الحجم للفرز
        volumes = {}
        for i in range(0, len(symbols), 100):
            batch = symbols[i:i+100]
            try:
                url2 = "https://api.itick.org/stock/quotes"
                params2 = {"region": "US", "codes": ",".join(batch)}
                r2 = requests.get(url2, headers=headers, params=params2, timeout=10)
                if r2.status_code == 200:
                    data2 = r2.json()
                    for sym, info in data2.get("data", {}).items():
                        volumes[sym] = info.get("v", 0)
                time.sleep(0.3)
            except:
                pass
        
        # 3. ترتيب حسب الحجم (الأعلى أولاً)
        sorted_symbols = sorted(volumes.items(), key=lambda x: x[1], reverse=True)
        top = [sym for sym, vol in sorted_symbols[:TOP_SYMBOLS]]
        
        print(f"[OK] Top {len(top)} symbols fetched")
        return top
        
    except Exception as e:
        print(f"Fetch top symbols error: {e}")
        return []

# ================= WEBSOCKET HANDLER =================
async def itick_websocket():
    global HOT_SYMBOLS
    
    # جلب أعلى 500 سهم قبل بدء WebSocket
    HOT_SYMBOLS = fetch_top_symbols()
    if not HOT_SYMBOLS:
        await send("⚠️ لم يتم العثور على أسهم. تحقق من المفتاح.")
        return
    
    await send(f"✅ *تم تحميل {len(HOT_SYMBOLS)} سهم نشط*")
    
    # تحويل الرموز إلى صيغة iTick
    symbols_param = ",".join([f"{sym}$US" for sym in HOT_SYMBOLS])
    
    uri = "wss://api.itick.org/stock"
    headers = {"token": ITICK_TOKEN}
    
    try:
        async with websockets.connect(uri, extra_headers=headers) as websocket:
            print("✅ متصل بـ iTick WebSocket")
            
            subscribe_msg = {
                "ac": "subscribe",
                "params": symbols_param,
                "types": "quote,tick"
            }
            await websocket.send(json.dumps(subscribe_msg))
            print(f"📡 تم الاشتراك في {len(HOT_SYMBOLS)} سهماً")
            
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
    change = data.get("change") or data.get("chp")
    
    if not symbol or not price:
        return
    
    if price < MIN_PRICE or price > MAX_PRICE:
        return
    if volume and volume < MIN_VOLUME:
        return
    
    if detect(symbol, price):
        if can_alert(symbol):
            previous = PRICE_CACHE[symbol]["previous"]
            change_pct = ((price - previous) / previous) * 100 if previous > 0 else 0
            score = get_signal_score(change_pct)
            
            today = time.strftime("%Y-%m-%d")
            if today not in DAILY_ALERTS:
                DAILY_ALERTS[today] = {}
            DAILY_ALERTS[today][symbol] = DAILY_ALERTS[today].get(symbol, 0) + 1
            
            msg = (
                f"🚨 *إشارة زخم فورية* 🚨\n\n"
                f"📊 الرمز: `{symbol}`\n"
                f"💰 السعر: `${price:.2f}`\n"
                f"📈 التغير: `+{change_pct:.2f}%`\n"
                f"🔥 القوة: `{score}/100`\n"
                f"🔢 التنبيه: `{DAILY_ALERTS[today][symbol]}`\n"
                f"🕒 {time.strftime('%H:%M:%S')}\n\n"
                f"⚠️ للمتابعة فقط"
            )
            
            await send(msg)
            print(f"📤 تم إرسال تنبيه لـ {symbol}")

# ================= MAIN =================
async def main():
    await send("🔥 *الماسح الفوري (WebSocket) يعمل*")
    print("🚀 بدء تشغيل WebSocket...")
    
    while True:
        try:
            await itick_websocket()
        except Exception as e:
            print(f"🔄 إعادة الاتصال: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
