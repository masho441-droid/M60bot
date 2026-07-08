# ====================== STRATEGY SETTINGS (محدثة) ======================
MIN_PRICE = 0.1
MAX_PRICE = 5.0
MIN_VOLUME = 200000
MIN_VOLUME_SPIKE = 5.0
MIN_PRICE_CHANGE = 5.0
MIN_ACCELERATION = 3.0
ALERT_COOLDOWN = 1800
SYMBOLS_LIMIT = 200

# ====================== FETCH HISTORICAL DATA (لحساب المتوسطات) =========
async def fetch_historical_data(symbol):
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period="1mo")
        if hist.empty:
            return None
        avg_volume_10 = hist["Volume"].iloc[-10:].mean()
        high_20d = hist["High"].iloc[-20:].max()
        return {"avg_volume_10": avg_volume_10, "high_20d": high_20d}
    except:
        return None

# ====================== DETECT EXPLOSION (محدثة) ========================
async def detect_explosion(quote):
    try:
        symbol = quote.get('symbol')
        price = quote.get('price')
        volume = quote.get('volume')
        change = quote.get('change_percent', 0)

        if not symbol or not price or not volume:
            return None

        # جلب البيانات التاريخية
        hist = await fetch_historical_data(symbol)
        if not hist:
            return None

        avg_volume_10 = hist["avg_volume_10"]
        high_20d = hist["high_20d"]

        volume_spike = volume / avg_volume_10 if avg_volume_10 > 0 else 1.0
        price_breakout = ((price - high_20d) / high_20d) * 100 if high_20d > 0 else 0

        # شروط الانفجار الكبير
        is_explosion = (
            MIN_PRICE <= price <= MAX_PRICE and
            volume >= MIN_VOLUME and
            volume_spike >= MIN_VOLUME_SPIKE and
            change > MIN_PRICE_CHANGE and
            price > high_20d
        )

        if is_explosion:
            target1 = price * 1.20
            target2 = price * 1.50
            target3 = price * 2.00
            stop_loss = price * 0.95

            return {
                "symbol": symbol,
                "price": price,
                "volume": volume,
                "volume_spike": volume_spike,
                "price_change": change,
                "price_breakout": price_breakout,
                "target1": target1,
                "target2": target2,
                "target3": target3,
                "stop_loss": stop_loss,
                "time": datetime.now(NY_TZ).strftime("%H:%M")
            }
        return None
    except Exception as e:
        print(f"⚠️ خطأ في تحليل {quote.get('symbol')}: {e}")
        return None
