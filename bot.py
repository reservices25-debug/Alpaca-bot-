import os
from datetime import datetime
import pytz
import alpaca_trade_api as tradeapi
from alpaca_trade_api.rest import TimeFrame

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BASE_URL = "https://api.alpaca.markets"

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version="v2")

symbols = [
    "JEPI", "JEPQ", "SCHD", "O", "SGOV",
    "SPY", "QQQ", "VTI", "XYLD", "QYLD"
]

ny = pytz.timezone("America/New_York")

cash_reserve_pct = 0.30
max_position_pct = 0.08
min_order_size = 1.00
max_trades_per_day = 8
max_open_positions = 3

take_profit_pct = 0.012
stop_loss_pct = -0.006
daily_loss_limit_pct = -0.02

min_entry_score = 5
min_hold_score = 3
volatility_limit = 0.018


def now_ny():
    return datetime.now(ny)


def log(msg):
    print(f"[{now_ny()}] {msg}")


def get_session():
    now = now_ny().time()

    if datetime.strptime("04:00", "%H:%M").time() <= now < datetime.strptime("09:30", "%H:%M").time():
        return "pre_market"

    if datetime.strptime("09:30", "%H:%M").time() <= now < datetime.strptime("16:00", "%H:%M").time():
        return "regular"

    if datetime.strptime("16:00", "%H:%M").time() <= now <= datetime.strptime("20:00", "%H:%M").time():
        return "after_hours"

    return "closed"


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
        log(f"Trade count error: {e}")
        return 0


def market_regime():
    try:
        bars = api.get_bars("SPY", TimeFrame.Day, limit=60).df

        if len(bars) < 50:
            return "neutral"

        close = bars["close"]
        price = close.iloc[-1]
        ma20 = close.tail(20).mean()
        ma50 = close.tail(50).mean()

        if price > ma20 > ma50:
            return "bullish"
        elif price < ma20 < ma50:
            return "bearish"

        return "neutral"

    except Exception as e:
        log(f"Market regime error: {e}")
        return "neutral"


def market_volatility_ok():
    try:
        bars = api.get_bars("SPY", TimeFrame.Minute, limit=30).df

        if len(bars) < 10:
            return False

        close = bars["close"]
        change = abs(close.iloc[-1] - close.iloc[0]) / close.iloc[0]

        log(f"SPY short volatility: {round(change * 100, 2)}%")

        return change <= volatility_limit

    except Exception as e:
        log(f"Volatility check error: {e}")
        return False


def candidate_symbols(regime):
    if regime == "bearish":
        return ["SGOV", "SCHD", "JEPI", "O"]

    if regime == "bullish":
        return ["QQQ", "SPY", "VTI", "JEPQ", "SCHD", "JEPI"]

    return ["SPY", "QQQ", "SCHD", "JEPI", "SGOV"]


def score_symbol(symbol):
    try:
        bars = api.get_bars(symbol, TimeFrame.Minute, limit=80).df

        if len(bars) < 60:
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
        momentum_50 = (last - close.iloc[-50]) / close.iloc[-50]

        avg_volume = volume.tail(20).mean()
        latest_volume = volume.iloc[-1]
        volume_ratio = latest_volume / avg_volume if avg_volume > 0 else 0

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
        if momentum_50 > 0:
            score += 1
        if volume_ratio >= 0.85:
            score += 1

        return score

    except Exception as e:
        log(f"Score failed for {symbol}: {e}")
        return -999


def submit_buy(symbol, amount):
    if amount < min_order_size:
        return False

    session = get_session()

    try:
        trade = api.get_latest_trade(symbol)
        last_price = float(trade.price)

        if session in ["pre_market", "after_hours"]:
            limit_price = round(last_price * 1.002, 2)

            log(f"EXTENDED BUY {symbol} ${round(amount, 2)} limit {limit_price}")

            api.submit_order(
                symbol=symbol,
                notional=round(amount, 2),
                side="buy",
                type="limit",
                limit_price=limit_price,
                time_in_force="day",
                extended_hours=True
            )

        elif session == "regular":
            log(f"REGULAR BUY {symbol} ${round(amount, 2)}")

            api.submit_order(
                symbol=symbol,
                notional=round(amount, 2),
                side="buy",
                type="market",
                time_in_force="day"
            )

        else:
            log("Market closed. No buy.")
            return False

        return True

    except Exception as e:
        log(f"Buy failed for {symbol}: {e}")
        return False


def submit_sell(symbol, qty):
    if qty <= 0:
        return False

    session = get_session()

    try:
        trade = api.get_latest_trade(symbol)
        last_price = float(trade.price)

        if session in ["pre_market", "after_hours"]:
            limit_price = round(last_price * 0.998, 2)

            log(f"EXTENDED SELL {symbol} qty {qty} limit {limit_price}")

            api.submit_order(
                symbol=symbol,
                qty=qty,
                side="sell",
                type="limit",
                limit_price=limit_price,
                time_in_force="day",
                extended_hours=True
            )

        elif session == "regular":
            log(f"REGULAR SELL {symbol} qty {qty}")

            api.submit_order(
                symbol=symbol,
                qty=qty,
                side="sell",
                type="market",
                time_in_force="day"
            )

        else:
            log("Market closed. No sell.")
            return False

        return True

    except Exception as e:
        log(f"Sell failed for {symbol}: {e}")
        return False


def manage_positions(regime):
    allowed = candidate_symbols(regime)

    for symbol in symbols:
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
            log(f"{symbol} profit target hit: {round(gain_pct * 100, 2)}%")
            submit_sell(symbol, qty)

        elif gain_pct <= stop_loss_pct:
            log(f"{symbol} stop loss hit: {round(gain_pct * 100, 2)}%")
            submit_sell(symbol, qty)

        elif symbol not in allowed:
            log(f"{symbol} no longer fits regime. Rotating out.")
            submit_sell(symbol, qty)

        elif score < min_hold_score:
            log(f"{symbol} weak score {score}. Rotating out.")
            submit_sell(symbol, qty)


def open_new_trades(regime):
    cash, equity, last_equity = get_account()

    if last_equity > 0:
        daily_change = (equity - last_equity) / last_equity

        if daily_change <= daily_loss_limit_pct:
            log("Daily loss limit hit. No new trades.")
            return

    if todays_trade_count() >= max_trades_per_day:
        log("Max trades reached today.")
        return

    open_positions = [s for s in symbols if get_position(s)]

    if len(open_positions) >= max_open_positions:
        log("Max open positions reached.")
        return

    candidates = candidate_symbols(regime)

    ranked = []

    for symbol in candidates:
        if get_position(symbol):
            continue

        score = score_symbol(symbol)
        log(f"{symbol} score: {score}")

        if score >= min_entry_score:
            ranked.append((symbol, score))

    ranked.sort(key=lambda x: x[1], reverse=True)

    if not ranked:
        log("No strong candidates.")
        return

    reserve_cash = equity * cash_reserve_pct
    investable_cash = cash - reserve_cash

    if investable_cash < min_order_size:
        log("Not enough investable cash.")
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
    log("----- EXTENDED HOURS BOT START -----")

    session = get_session()
    log(f"Session: {session}")

    if session == "closed":
        log("Market fully closed. No trades.")
        return

    regime = market_regime()
    log(f"Market regime: {regime}")

    if session == "regular":
        if not market_volatility_ok():
            log("Volatility too high. Defensive pause.")
            return

        manage_positions(regime)
        open_new_trades(regime)

    elif session in ["pre_market", "after_hours"]:
        log("Extended-hours mode active.")

        # Safer extended-hours behavior:
        # Manage exits, but only open new trades if score is strong.
        manage_positions(regime)
        open_new_trades(regime)

    log("----- EXTENDED HOURS BOT END -----")


if __name__ == "__main__":
    run_bot()
