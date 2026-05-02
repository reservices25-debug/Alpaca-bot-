import os
import csv
from pathlib import Path
from datetime import datetime
import pytz
import alpaca_trade_api as tradeapi
from alpaca_trade_api.rest import TimeFrame

# =====================
# API SETUP
# =====================

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")

api = tradeapi.REST(API_KEY, SECRET_KEY, "https://api.alpaca.markets", api_version="v2")

ny = pytz.timezone("America/New_York")

# =====================
# FULL MULTI-ASSET UNIVERSE
# =====================

symbols = [
    # Core
    "SPY","QQQ","VTI","VOO","DIA","IWM",

    # Income
    "JEPI","JEPQ","SCHD","VYM","SPHD","XYLD","QYLD",

    # Cash
    "SGOV","BIL","SHV",

    # Tech
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA",

    # Financials
    "JPM","BAC","V","MA",

    # Defensive
    "KO","PEP","PG","JNJ","WMT","T",

    # Energy
    "XOM","CVX","XLE",

    # Sectors
    "XLK","XLF","XLV","XLP","XLY",

    # 🟡 Metals
    "GLD","IAU","GDX","NEM","GOLD",
    "SLV","SIVR","AG","WPM",
    "PPLT","PALL",

    # 🌾 Commodities
    "DBC","GSG","USO","UNG","CORN","WEAT","SOYB",

    # 💱 Currency ETFs
    "UUP","FXE","FXY","FXB","FXA","CYB",

    # REITs
    "O","STAG","MAIN"
]

# =====================
# SETTINGS
# =====================

cash_reserve_pct = 0.30
base_position_pct = 0.06
min_position_pct = 0.03
max_position_pct = 0.08
min_order_size = 1.00

max_trades_per_day = 10
max_open_positions = 4

take_profit_pct = 0.018
profit_lock_pct = 0.006
stop_loss_pct = -0.005
daily_loss_limit_pct = -0.02

min_entry_score = 4
min_hold_score = 2

# =====================
# HELPERS
# =====================

def now():
    return datetime.now(ny)

def log(msg):
    print(f"[{now()}] {msg}")

def get_account():
    a = api.get_account()
    return float(a.cash), float(a.equity), float(a.last_equity)

def get_position(sym):
    try:
        return api.get_position(sym)
    except:
        return None

def trade_count():
    try:
        start = now().replace(hour=0, minute=0, second=0)
        acts = api.get_activities(activity_types="FILL", after=start.isoformat())
        return len(acts)
    except:
        return 0

# =====================
# MARKET LOGIC
# =====================

def hedge_mode():
    try:
        spy = api.get_bars("SPY", TimeFrame.Day, limit=20).df["close"]
        qqq = api.get_bars("QQQ", TimeFrame.Day, limit=20).df["close"]

        return spy.iloc[-1] < spy.mean() or qqq.iloc[-1] < qqq.mean()
    except:
        return False

# =====================
# SCORING
# =====================

def score(sym):
    try:
        bars = api.get_bars(sym, TimeFrame.Minute, limit=60).df
        close = bars["close"]

        last = close.iloc[-1]
        ma5 = close.tail(5).mean()
        ma20 = close.tail(20).mean()

        s = 0
        if last > ma5: s += 1
        if ma5 > ma20: s += 1
        if last > ma20: s += 1

        return s
    except:
        return -999

def rank():
    r = [(s, score(s)) for s in symbols]
    r.sort(key=lambda x: x[1], reverse=True)
    return r

# =====================
# TRADING
# =====================

def buy(sym, amt):
    if amt < min_order_size:
        return False
    api.submit_order(symbol=sym, notional=round(amt,2), side="buy", type="market", time_in_force="day")
    log(f"BUY {sym}")
    return True

def sell(sym, qty, reason):
    api.submit_order(symbol=sym, qty=qty, side="sell", type="market", time_in_force="day")
    log(f"SELL {sym} | {reason}")

# =====================
# POSITION MANAGEMENT
# =====================

def manage():
    ranked = rank()
    top = [s for s,_ in ranked[:max_open_positions]]

    for sym in symbols:
        p = get_position(sym)
        if not p:
            continue

        qty = float(p.qty)
        entry = float(p.avg_entry_price)
        price = float(p.current_price)

        gain = (price - entry) / entry
        sc = score(sym)

        if gain >= take_profit_pct:
            sell(sym, qty, "TAKE PROFIT")
            continue

        if gain >= profit_lock_pct and sc < min_hold_score:
            sell(sym, qty, "LOCK PROFIT")
            continue

        if gain <= stop_loss_pct:
            sell(sym, qty, "STOP LOSS")
            continue

        if gain < 0 and sym not in top:
            sell(sym, qty, "ROTATE")

# =====================
# ENTRY ENGINE
# =====================

def enter():
    cash, equity, last = get_account()

    if last > 0:
        change = (equity - last) / last
        if change <= daily_loss_limit_pct:
            log("DAILY LOSS LIMIT HIT")
            return

    if trade_count() >= max_trades_per_day:
        return

    ranked = rank()
    open_pos = [s for s in symbols if get_position(s)]

    slots = max_open_positions - len(open_pos)
    if slots <= 0:
        return

    investable = cash - (equity * cash_reserve_pct)

    for sym, sc in ranked:
        if slots <= 0:
            break
        if sc < min_entry_score:
            continue
        if get_position(sym):
            continue

        amt = min(equity * base_position_pct, investable)

        if buy(sym, amt):
            slots -= 1
            investable -= amt

# =====================
# MAIN
# =====================

def run():
    log("START BOT")

    if hedge_mode():
        log("SMART HEDGE MODE ACTIVE")

    manage()
    enter()

    log("END BOT")

if __name__ == "__main__":
    run()
