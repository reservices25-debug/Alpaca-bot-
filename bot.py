import os
from datetime import datetime
import pytz
import alpaca_trade_api as tradeapi
from alpaca_trade_api.rest import TimeFrame

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BASE_URL = "https://api.alpaca.markets"

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL)

symbols = ["JEPI", "JEPQ", "SCHD", "O", "SGOV", "SPY", "QQQ", "VTI", "XYLD", "QYLD"]

ny = pytz.timezone("America/New_York")

# === CONFIG ===
cash_reserve_pct = 0.30
max_position_pct = 0.08
min_order_size = 1.00

max_trades_per_day = 8
max_open_positions = 3

take_profit_pct = 0.01
stop_loss_pct = -0.006

daily_loss_limit_pct = -0.02
volatility_threshold = 0.02  # skip market if too volatile


# === UTILS ===
def now():
    return datetime.now(ny)


def log(msg):
    print(f"[{now()}] {msg}")


def is_market_open():
    return api.get_clock().is_open


def get_account():
    acc = api.get_account()
    return float(acc.cash), float(acc.equity), float(acc.last_equity)


def get_position(symbol):
    try:
        return api.get_position(symbol)
    except:
        return None


# === RISK SYSTEM ===
def daily_drawdown():
    _, equity, last_equity = get_account()
    return (equity - last_equity) / last_equity


def kill_switch():
    dd = daily_drawdown()
    if dd <= daily_loss_limit_pct:
        log(f"KILL SWITCH TRIGGERED: {round(dd*100,2)}%")
        return True
    return False


# === MARKET STATE ===
def market_regime():
    bars = api.get_bars("SPY", TimeFrame.Day, limit=50).df

    close = bars["close"]
    price = close.iloc[-1]
    ma20 = close.tail(20).mean()
    ma50 = close.tail(50).mean()

    if price > ma20 > ma50:
        return "bull"
    elif price < ma20 < ma50:
        return "bear"
    return "neutral"


def market_volatility():
    bars = api.get_bars("SPY", TimeFrame.Minute, limit=30).df
    close = bars["close"]

    change = abs(close.iloc[-1] - close.iloc[0]) / close.iloc[0]
    return change


# === SCORING ===
def score(symbol):
    try:
        bars = api.get_bars(symbol, TimeFrame.Minute, limit=60).df
        close = bars["close"]

        ma5 = close.tail(5).mean()
        ma20 = close.tail(20).mean()

        last = close.iloc[-1]
        prev = close.iloc[-2]

        score = 0

        if last > ma5:
            score += 1
        if ma5 > ma20:
            score += 1
        if last > prev:
            score += 1

        return score
    except:
        return -999


# === TRADING ===
def buy(symbol, amount):
    if amount < min_order_size:
        return

    log(f"BUY {symbol} ${round(amount,2)}")

    api.submit_order(
        symbol=symbol,
        notional=round(amount, 2),
        side="buy",
        type="market",
        time_in_force="day"
    )


def sell(symbol, qty):
    log(f"SELL {symbol}")

    api.submit_order(
        symbol=symbol,
        qty=qty,
        side="sell",
        type="market",
        time_in_force="day"
    )


# === POSITION MANAGEMENT ===
def manage_positions(regime):
    for s in symbols:
        pos = get_position(s)
        if not pos:
            continue

        qty = float(pos.qty)
        entry = float(pos.avg_entry_price)
        price = float(pos.current_price)

        pnl = (price - entry) / entry

        if pnl >= take_profit_pct:
            log(f"{s} TAKE PROFIT")
            sell(s, qty)

        elif pnl <= stop_loss_pct:
            log(f"{s} STOP LOSS")
            sell(s, qty)

        elif regime == "bear" and s not in ["SGOV", "JEPI", "SCHD"]:
            log(f"{s} DEFENSIVE EXIT")
            sell(s, qty)


# === ENTRY ENGINE ===
def open_positions(regime):
    cash, equity, _ = get_account()

    reserve = equity * cash_reserve_pct
    available = cash - reserve

    if available < min_order_size:
        return

    ranked = []

    for s in symbols:
        if get_position(s):
            continue

        sc = score(s)
        if sc >= 2:
            ranked.append((s, sc))

    ranked.sort(key=lambda x: x[1], reverse=True)

    open_count = len([s for s in symbols if get_position(s)])

    for s, sc in ranked:
        if open_count >= max_open_positions:
            break

        amount = min(equity * max_position_pct, available)

        buy(s, amount)

        available -= amount
        open_count += 1


# === MAIN ===
def run():
    log("START BOT")

    if not is_market_open():
        log("MARKET CLOSED")
        return

    if kill_switch():
        return

    vol = market_volatility()
    if vol > volatility_threshold:
        log(f"VOLATILITY TOO HIGH: {round(vol*100,2)}%")
        return

    current_time = now().time()

    # trading window (avoid open chaos + close chaos)
    if current_time < datetime.strptime("10:00", "%H:%M").time() or \
       current_time > datetime.strptime("15:30", "%H:%M").time():
        log("OUTSIDE TRADING WINDOW")
        return

    regime = market_regime()
    log(f"REGIME: {regime}")

    manage_positions(regime)
    open_positions(regime)

    log("END BOT")


if __name__ == "__main__":
    run()
