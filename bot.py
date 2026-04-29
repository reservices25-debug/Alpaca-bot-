import os
from datetime import datetime
import pytz
import alpaca_trade_api as tradeapi
from alpaca_trade_api.rest import TimeFrame

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BASE_URL = "https://api.alpaca.markets"

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version="v2")

symbols = ["JEPI", "JEPQ", "SCHD", "O", "SGOV", "SPY", "QQQ", "VTI", "XYLD", "QYLD"]

ny = pytz.timezone("America/New_York")

cash_reserve_pct = 0.30
max_position_pct = 0.08
min_order_size = 1.00
max_trades_per_day = 8
max_open_positions = 3

take_profit_pct = 0.01
stop_loss_pct = -0.006
daily_loss_limit_pct = -0.02

min_entry_score = 4
min_hold_score = 3


def now_ny():
    return datetime.now(ny)


def is_market_open():
    return api.get_clock().is_open


def get_account():
    account = api.get_account()
    return float(account.cash), float(account.equity), float(account.last_equity)


def get_position(symbol):
    try:
        return api.get_position(symbol)
    except Exception:
        return None


def todays_trade_count():
    try:
        start = now_ny().replace(hour=0, minute=0, second=0, microsecond=0)
        activities = api.get_activities(activity_types="FILL", after=start.isoformat())
        return len(activities)
    except Exception as e:
        print("Trade count error:", e)
        return 0


def market_regime():
    try:
        bars = api.get_bars("SPY", TimeFrame.Day, limit=50).df

        if len(bars) < 30:
            return "neutral"

        close = bars["close"]
        price = close.iloc[-1]
        ma20 = close.tail(20).mean()
        ma50 = close.tail(50).mean()

        if price > ma20 > ma50:
            return "bullish"
        elif price < ma20 < ma50:
            return "bearish"
        else:
            return "neutral"

    except Exception as e:
        print("Market regime error:", e)
        return "neutral"


def score_symbol(symbol):
    try:
        bars = api.get_bars(symbol, TimeFrame.Minute, limit=60).df

        if len(bars) < 50:
            return -999

        close = bars["close"]
        volume = bars["volume"]

        last = close.iloc[-1]
        prev = close.iloc[-2]

        ma5 = close.tail(5).mean()
        ma20 = close.tail(20).mean()
        ma50 = close.tail(50).mean()

        momentum_1 = (last - prev) / prev
        momentum_20 = (last - close.iloc[-20]) / close.iloc[-20]

        avg_volume = volume.tail(20).mean()
        latest_volume = volume.iloc[-1]
        volume_score = latest_volume / avg_volume if avg_volume > 0 else 0

        score = 0

        if last > ma5:
            score += 1
        if ma5 > ma20:
            score += 1
        if ma20 > ma50:
            score += 1
        if momentum_1 > 0:
            score += 1
        if momentum_20 > 0:
            score += 1
        if volume_score >= 0.80:
            score += 1

        return score

    except Exception as e:
        print(f"Score failed for {symbol}: {e}")
        return -999


def candidate_symbols_by_regime(regime):
    if regime == "bearish":
        return ["SGOV", "JEPI", "SCHD", "O"]
    elif regime == "bullish":
        return ["QQQ", "SPY", "VTI", "JEPQ", "SCHD", "JEPI"]
    else:
        return ["SPY", "QQQ", "JEPI", "JEPQ", "SCHD", "SGOV"]


def submit_buy(symbol, amount):
    if amount < min_order_size:
        return False

    print(f"BUY {symbol} ${round(amount, 2)}")

    try:
        api.submit_order(
            symbol=symbol,
            notional=round(amount, 2),
            side="buy",
            type="market",
            time_in_force="day"
        )
        return True
    except Exception as e:
        print(f"Buy failed for {symbol}: {e}")
        return False


def submit_sell(symbol, qty):
    if qty <= 0:
        return False

    print(f"SELL {symbol} qty {qty}")

    try:
        api.submit_order(
            symbol=symbol,
            qty=qty,
            side="sell",
            type="market",
            time_in_force="day"
        )
        return True
    except Exception as e:
        print(f"Sell failed for {symbol}: {e}")
        return False


def manage_positions(regime):
    trades = 0
    allowed = candidate_symbols_by_regime(regime)

    for symbol in symbols:
        if trades >= max_trades_per_day:
            break

        position = get_position(symbol)

        if not position:
            continue

        qty = float(position.qty)
        avg_entry = float(position.avg_entry_price)
        current_price = float(position.current_price)

        if avg_entry <= 0:
            continue

        gain_pct = (current_price - avg_entry) / avg_entry
        score = score_symbol(symbol)

        if gain_pct >= take_profit_pct:
            print(f"{symbol} profit target hit: {round(gain_pct * 100, 2)}%")
            if submit_sell(symbol, qty):
                trades += 1
            continue

        if gain_pct <= stop_loss_pct:
            print(f"{symbol} stop loss hit: {round(gain_pct * 100, 2)}%")
            if submit_sell(symbol, qty):
                trades += 1
            continue

        if symbol not in allowed:
            print(f"{symbol} no longer fits regime → rotating out")
            if submit_sell(symbol, qty):
                trades += 1
            continue

        if score < min_hold_score:
            print(f"{symbol} score dropped to {score} → rotating out")
            if submit_sell(symbol, qty):
                trades += 1
            continue


def open_new_trades(regime):
    cash, equity, last_equity = get_account()

    daily_change = (equity - last_equity) / last_equity if last_equity > 0 else 0

    if daily_change <= daily_loss_limit_pct:
        print("Daily loss limit hit. No new trades.")
        return

    if todays_trade_count() >= max_trades_per_day:
        print("Max trades reached today.")
        return

    candidates = candidate_symbols_by_regime(regime)

    ranked = []

    for symbol in candidates:
        if get_position(symbol):
            continue

        score = score_symbol(symbol)
        print(f"{symbol} score: {score}")

        if score >= min_entry_score:
            ranked.append((symbol, score))

    ranked.sort(key=lambda x: x[1], reverse=True)

    if not ranked:
        print("No strong candidates.")
        return

    open_positions = [s for s in symbols if get_position(s)]

    if len(open_positions) >= max_open_positions:
        print("Max open positions reached.")
        return

    reserve_cash = equity * cash_reserve_pct
    investable_cash = cash - reserve_cash

    if investable_cash < min_order_size:
        print("Not enough investable cash.")
        return

    for symbol, score in ranked:
        if todays_trade_count() >= max_trades_per_day:
            break

        if len([s for s in symbols if get_position(s)]) >= max_open_positions:
            break

        amount = min(equity * max_position_pct, investable_cash)

        if submit_buy(symbol, amount):
            investable_cash -= amount


def run_bot():
    print("----- INSTITUTIONAL STEP 2 BOT START -----")
    print(f"Time NY: {now_ny()}")

    if not is_market_open():
        print("Market closed. No trades.")
        return

    regime = market_regime()
    print(f"Market regime: {regime}")

    manage_positions(regime)
    open_new_trades(regime)

    print("----- INSTITUTIONAL STEP 2 BOT END -----")


if __name__ == "__main__":
    run_bot()
