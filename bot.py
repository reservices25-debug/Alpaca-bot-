import os
import csv
from pathlib import Path
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

TRADE_LOG = "trade_log.csv"
SNAPSHOT_LOG = "portfolio_snapshot.csv"
RISK_REPORT = "risk_report.txt"
PERFORMANCE_REPORT = "performance_report.txt"

cash_reserve_pct = 0.30
base_position_pct = 0.08
min_position_pct = 0.03
max_position_pct = 0.10
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


def write_csv_row(file_name, headers, row):
    exists = Path(file_name).exists()
    with open(file_name, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def get_session():
    t = now_ny().time()

    if datetime.strptime("04:00", "%H:%M").time() <= t < datetime.strptime("09:30", "%H:%M").time():
        return "pre_market"
    if datetime.strptime("09:30", "%H:%M").time() <= t < datetime.strptime("16:00", "%H:%M").time():
        return "regular"
    if datetime.strptime("16:00", "%H:%M").time() <= t <= datetime.strptime("20:00", "%H:%M").time():
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
        acts = api.get_activities(activity_types="FILL", after=start.isoformat())
        return len(acts)
    except Exception:
        return 0


def log_trade(action, symbol, qty=None, amount=None, price=None, reason="", strategy=""):
    write_csv_row(
        TRADE_LOG,
        ["time", "action", "symbol", "qty", "amount", "price", "reason", "strategy"],
        {
            "time": str(now_ny()),
            "action": action,
            "symbol": symbol,
            "qty": qty,
            "amount": amount,
            "price": price,
            "reason": reason,
            "strategy": strategy
        }
    )


def save_portfolio_snapshot():
    cash, equity, last_equity = get_account()

    write_csv_row(
        SNAPSHOT_LOG,
        ["time", "cash", "equity", "last_equity"],
        {
            "time": str(now_ny()),
            "cash": cash,
            "equity": equity,
            "last_equity": last_equity
        }
    )


def analyze_performance():
    if not Path(TRADE_LOG).exists():
        return {
            "trades": 0,
            "best_symbol": None,
            "worst_symbol": None,
            "symbol_counts": {}
        }

    counts = {}

    with open(TRADE_LOG, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    for r in rows:
        symbol = r.get("symbol")
        if symbol:
            counts[symbol] = counts.get(symbol, 0) + 1

    best_symbol = max(counts, key=counts.get) if counts else None
    worst_symbol = min(counts, key=counts.get) if counts else None

    return {
        "trades": len(rows),
        "best_symbol": best_symbol,
        "worst_symbol": worst_symbol,
        "symbol_counts": counts
    }


def save_performance_report():
    perf = analyze_performance()

    with open(PERFORMANCE_REPORT, "w") as f:
        f.write("STEP 11 PERFORMANCE REPORT\n")
        f.write("==========================\n")
        f.write(f"Time: {now_ny()}\n")
        f.write(f"Total logged trades: {perf['trades']}\n")
        f.write(f"Most active symbol: {perf['best_symbol']}\n")
        f.write(f"Least active symbol: {perf['worst_symbol']}\n")
        f.write(f"Symbol counts: {perf['symbol_counts']}\n")


def save_risk_report(session, regime):
    cash, equity, last_equity = get_account()
    daily_change = (equity - last_equity) / last_equity if last_equity > 0 else 0

    with open(RISK_REPORT, "w") as f:
        f.write("STEP 11 INSTITUTIONAL-STYLE RISK REPORT\n")
        f.write("=======================================\n")
        f.write(f"Time: {now_ny()}\n")
        f.write(f"Session: {session}\n")
        f.write(f"Regime: {regime}\n")
        f.write(f"Cash: ${round(cash, 2)}\n")
        f.write(f"Equity: ${round(equity, 2)}\n")
        f.write(f"Last equity: ${round(last_equity, 2)}\n")
        f.write(f"Daily change: {round(daily_change * 100, 2)}%\n")
        f.write(f"Trades today: {todays_trade_count()}\n")


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
        if price < ma20 < ma50:
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


def score_trend(symbol):
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
        log(f"Trend score failed for {symbol}: {e}")
        return -999


def score_mean_reversion(symbol):
    try:
        bars = api.get_bars(symbol, TimeFrame.Minute, limit=40).df
        if len(bars) < 30:
            return -999

        close = bars["close"]
        last = close.iloc[-1]

        ma20 = close.tail(20).mean()
        recent_low = close.tail(20).min()

        discount_from_ma = (ma20 - last) / ma20 if ma20 > 0 else 0
        bounce_from_low = (last - recent_low) / recent_low if recent_low > 0 else 0

        score = 0

        if discount_from_ma > 0.002:
            score += 2
        if bounce_from_low > 0.001:
            score += 2
        if last > recent_low:
            score += 1

        return score

    except Exception as e:
        log(f"Mean reversion score failed for {symbol}: {e}")
        return -999


def choose_strategy(regime):
    if regime == "bullish":
        return "trend"
    if regime == "bearish":
        return "defensive"
    return "mean_reversion"


def adaptive_position_pct(symbol, strategy):
    perf = analyze_performance()
    counts = perf["symbol_counts"]

    pct = base_position_pct

    if symbol == perf["best_symbol"]:
        pct += 0.01

    if symbol == perf["worst_symbol"]:
        pct -= 0.01

    if strategy == "defensive":
        pct = min(pct, 0.05)

    if counts.get(symbol, 0) == 0:
        pct = base_position_pct

    return max(min_position_pct, min(max_position_pct, pct))


def submit_buy(symbol, amount, strategy):
    if amount < min_order_size:
        return False

    session = get_session()

    try:
        trade = api.get_latest_trade(symbol)
        last_price = float(trade.price)

        if session in ["pre_market", "after_hours"]:
            limit_price = round(last_price * 1.002, 2)
            log(f"EXT BUY {symbol} ${round(amount, 2)} limit {limit_price}")

            api.submit_order(
                symbol=symbol,
                notional=round(amount, 2),
                side="buy",
                type="limit",
                limit_price=limit_price,
                time_in_force="day",
                extended_hours=True
            )

            log_trade("BUY", symbol, amount=round(amount, 2), price=limit_price, reason="extended_entry", strategy=strategy)

        elif session == "regular":
            log(f"REG BUY {symbol} ${round(amount, 2)}")

            api.submit_order(
                symbol=symbol,
                notional=round(amount, 2),
                side="buy",
                type="market",
                time_in_force="day"
            )

            log_trade("BUY", symbol, amount=round(amount, 2), price=last_price, reason="regular_entry", strategy=strategy)

        else:
            log("Closed. No buy.")
            return False

        return True

    except Exception as e:
        log(f"Buy failed for {symbol}: {e}")
        return False


def submit_sell(symbol, qty, reason, strategy):
    if qty <= 0:
        return False

    session = get_session()

    try:
        trade = api.get_latest_trade(symbol)
        last_price = float(trade.price)

        if session in ["pre_market", "after_hours"]:
            limit_price = round(last_price * 0.998, 2)
            log(f"EXT SELL {symbol} qty {qty} limit {limit_price}")

            api.submit_order(
                symbol=symbol,
                qty=qty,
                side="sell",
                type="limit",
                limit_price=limit_price,
                time_in_force="day",
                extended_hours=True
            )

            log_trade("SELL", symbol, qty=qty, price=limit_price, reason=reason, strategy=strategy)

        elif session == "regular":
            log(f"REG SELL {symbol} qty {qty}")

            api.submit_order(
                symbol=symbol,
                qty=qty,
                side="sell",
                type="market",
                time_in_force="day"
            )

            log_trade("SELL", symbol, qty=qty, price=last_price, reason=reason, strategy=strategy)

        else:
            log("Closed. No sell.")
            return False

        return True

    except Exception as e:
        log(f"Sell failed for {symbol}: {e}")
        return False


def manage_positions(regime, strategy):
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

        trend_score = score_trend(symbol)
        hold_score = trend_score

        if gain_pct >= take_profit_pct:
            log(f"{symbol} take profit {round(gain_pct * 100, 2)}%")
            submit_sell(symbol, qty, "take_profit", strategy)

        elif gain_pct <= stop_loss_pct:
            log(f"{symbol} stop loss {round(gain_pct * 100, 2)}%")
            submit_sell(symbol, qty, "stop_loss", strategy)

        elif symbol not in allowed:
            log(f"{symbol} regime rotation out")
            submit_sell(symbol, qty, "regime_rotation", strategy)

        elif hold_score < min_hold_score:
            log(f"{symbol} weak score {hold_score}")
            submit_sell(symbol, qty, "weak_score", strategy)


def open_new_trades(regime, strategy):
    cash, equity, last_equity = get_account()

    if last_equity > 0:
        daily_change = (equity - last_equity) / last_equity
        if daily_change <= daily_loss_limit_pct:
            log("Daily loss limit hit. No new trades.")
            return

    if todays_trade_count() >= max_trades_per_day:
        log("Max trades reached.")
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

        if strategy == "trend":
            score = score_trend(symbol)
        elif strategy == "mean_reversion":
            score = score_mean_reversion(symbol)
        else:
            score = score_trend(symbol)

        log(f"{symbol} {strategy} score: {score}")

        if score >= min_entry_score:
            ranked.append((symbol, score))

    ranked.sort(key=lambda x: x[1], reverse=True)

    if not ranked:
        log("No strong candidates.")
        return

    reserve = equity * cash_reserve_pct
    investable_cash = cash - reserve

    if investable_cash < min_order_size:
        log("Not enough investable cash.")
        return

    for symbol, score in ranked:
        if todays_trade_count() >= max_trades_per_day:
            break

        if len([s for s in symbols if get_position(s)]) >= max_open_positions:
            break

        position_pct = adaptive_position_pct(symbol, strategy)
        amount = min(equity * position_pct, investable_cash)

        if submit_buy(symbol, amount, strategy):
            investable_cash -= amount


def run_bot():
    log("----- STEP 11 MULTI-STRATEGY BOT START -----")

    session = get_session()
    log(f"Session: {session}")

    regime = market_regime()
    strategy = choose_strategy(regime)

    log(f"Regime: {regime}")
    log(f"Strategy: {strategy}")

    if session == "closed":
        log("Market closed. Reports only.")
        save_portfolio_snapshot()
        save_risk_report(session, regime)
        save_performance_report()
        return

    if session == "regular":
        if not market_volatility_ok():
            log("Volatility too high. Pause.")
            save_portfolio_snapshot()
            save_risk_report(session, regime)
            save_performance_report()
            return

    manage_positions(regime, strategy)
    open_new_trades(regime, strategy)

    save_portfolio_snapshot()
    save_risk_report(session, regime)
    save_performance_report()

    log("----- STEP 11 MULTI-STRATEGY BOT END -----")


if __name__ == "__main__":
    run_bot()
