import os
import asyncio
import requests
import time
from datetime import datetime, timedelta
import pytz
from telegram import Bot

TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
bot = Bot(token=TOKEN)

# ==================== المعايير ====================
MIN_PRICE = 0.1
MAX_PRICE = 10.0
MIN_CHANGE = 1.0
MIN_VOLUME = 50000
UPDATE_THRESHOLD = 0.03  # 3% زيادة لتحديث التنبيه

last_values = {}
alert_counters = {}
avg_volume_cache = {}

# ==================== دوال مساعدة ====================
def get_avg_volume(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1mo"
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        data = r.json()
        volumes = [v for v in data['chart']['result'][0]['indicators']['quote'][0]['volume'] if v]
        if len(volumes) >= 20:
            return sum(volumes[-20:]) / 20
    except:
        pass
    return 500000

def is_volume_accelerating(volumes):
    if len(volumes) < 6:
        return False
    last_vol = volumes[-1]
    avg_5min = sum(volumes[-6:-1]) / 5
    return last_vol >= avg_5min * 2

def calculate_momentum_acceleration(price_history):
    if len(price_history) < 3:
        return 0
    change_1 = (price_history[-1] - price_history[-2]) / price_history[-2] * 100
    change_2 = (price_history[-2] - price_history[-3]) / price_history[-3] * 100
    return change_1 - change_2

def get_ny_time():
    return datetime.now(pytz.timezone('America/New_York'))

def is_market_active():
    ny_now = get_ny_time()
    return ny_now.weekday() < 5  # الإثنين إلى الجمعة

async def send_msg(text):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        print(f"خطأ في الإرسال: {e}")

# ==================== جلب البيانات ====================
def fetch_stock_data(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        data = r.json()
        res = data['chart']['result'][0]['meta']
        price = res.get('regularMarketPrice')
        vol = res.get('regularMarketVolume')
        if price is None or vol is None:
            return None
        prev = res.get('previousClose', price)
        change = ((price - prev) / prev) * 100
        
        volumes = [v for v in data['chart']['result'][0]['indicators']['quote'][0]['volume'] if v]
        price_history = [c for c in data['chart']['result'][0]['indicators']['quote'][0]['close'] if c]
        
        return {
            "price": price,
            "volume": vol,
            "change": change,
            "volumes": volumes,
            "price_history": price_history
        }
    except Exception as e:
        print(f"خطأ في {symbol}: {e}")
        return None

# ==================== إرسال التنبيه ====================
async def send_alert(symbol, price, change, volume_ratio, alert_num):
    if alert_num == 1:
        strength_text = "📈 بداية انطلاق"
        success_rate = "65% - 75%"
    else:
        strength_text = "🚀 تحديث زخم"
        success_rate = "75% - 85%"
    
    target1 = price * 1.05
    target2 = price * 1.08
    target3 = price * 1.12
    stop = price * 0.97
    
    msg = (
        f"🔥 *تنبيه استراتيجي - صيد الانفجارات* 🔥\n\n"
        f"⏰ *الوقت:* {get_ny_time().strftime('%H:%M:%S')}\n"
        f"🔴 *الرمز:* {symbol}\n"
        f"📊 *رقم التنبيه:* {alert_num}\n"
        f"📈 *الحالة:* {strength_text}\n\n"
        f"💰 *السعر:* ${price:.2f}\n"
        f"📈 *الصعود:* +{change:.2f}%\n"
        f"📊 *الحجم النسبي:* {volume_ratio:.2f}x\n\n"
        f"🎯 *الأهداف المتوقعة:*\n"
        f"🟢 *الهدف الأول:* ${target1:.2f}  (+5.0%)\n"
        f"🟡 *الهدف الثاني:* ${target2:.2f}  (+8.0%)\n"
        f"🔴 *الهدف الثالث:* ${target3:.2f}  (+12.0%)\n\n"
        f"🛑 *وقف الخسارة:* ${stop:.2f}  (-3.0%)\n"
        f"📈 *نسبة النجاح المتوقعة:* {success_rate}\n\n"
        f"✨ *تم اكتشاف السهم بواسطة خوارزمية M60 Hunter* ✨"
    )
    await send_msg(msg)

# ==================== الحلقة الرئيسية ====================
async def main():
    await send_msg("✅ *نظام الرصد المتطور (بدون MBI) يعمل الآن*")
    print("--- البوت يعمل ---")

    while True:
        if not is_market_active():
            print("⏸️ نهاية الأسبوع (السبت أو الأحد). إعادة تعيين المتتبع وإيقاف الفحص...")
            last_values.clear()
            alert_counters.clear()
            await asyncio.sleep(3600)
            continue

        stocks = ["RIVN", "LCID", "QS", "CLOV", "WKHS", "MULN", "PLTR", "SOFI", "BB", "HUT"]
        
        for symbol in stocks:
            data = fetch_stock_data(symbol)
            if not data:
                continue
            
            price = data["price"]
            volume = data["volume"]
            change = data["change"]
            volumes = data["volumes"]
            price_history = data["price_history"]
            
            if price < MIN_PRICE or price > MAX_PRICE or volume < MIN_VOLUME:
                continue
            
            if symbol not in avg_volume_cache:
                avg_volume_cache[symbol] = get_avg_volume(symbol)
            avg_vol = avg_volume_cache[symbol]
            volume_ratio = volume / avg_vol if avg_vol > 0 else 1.0
            
            momentum_acc = calculate_momentum_acceleration(price_history)
            vol_acc = is_volume_accelerating(volumes)
            
            # ===== شرط التنبيه الأول (بدون MBI) =====
            if symbol not in last_values:
                if change >= MIN_CHANGE and momentum_acc > 0 and vol_acc:
                    last_values[symbol] = {"price": price, "change": change, "rel_vol": volume_ratio}
                    alert_counters[symbol] = 1
                    await send_alert(symbol, price, change, volume_ratio, 1)
            else:
                # ===== شرط التحديث (زيادة 3%) =====
                if price >= last_values[symbol]["price"] * (1 + UPDATE_THRESHOLD):
                    last_values[symbol] = {"price": price, "change": change, "rel_vol": volume_ratio}
                    alert_counters[symbol] = alert_counters.get(symbol, 0) + 1
                    await send_alert(symbol, price, change, volume_ratio, alert_counters[symbol])
        
        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
