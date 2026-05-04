import os
import csv
import json
from pathlib import Path
from datetime import datetime
import pytz
import numpy as np
import alpaca_trade_api as tradeapi
from alpaca_trade_api.rest import TimeFrame

try:
    from sklearn.linear_model import LogisticRegression
    ML_AVAILABLE = True
except Exception:
    ML_AVAILABLE = False

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BASE_URL = "https://api.alpaca.markets"

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version="v2")
ny = pytz.timezone("America/New_York")

symbols = [
    "SPY","QQQ","VTI","VOO","DIA","IWM",
    "JEPI","JEPQ","SCHD","VYM","SPHD","XYLD","QYLD",
    "SGOV","BIL","SHV",
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA",
    "JPM","BAC","V","MA",
    "KO","PEP","PG","JNJ","WMT","T",
    "XOM","CVX","XLE",
    "XLK","XLF","XLV","XLP","XLY",
    "GLD","IAU","GDX","NEM","GOLD",
    "SLV","SIVR","AG","WPM","PPLT","PALL",
    "DBC","GSG","USO","UNG","CORN","WEAT","SOYB",
    "UUP","FXE","FXY","FXB","FXA","CYB",
    "O","STAG","MAIN"
]

TRADE_LOG = "trade_log.csv"
SNAPSHOT_LOG = "portfolio_snapshot.csv"
RISK_REPORT = "risk_report.txt"
PERFORMANCE_REPORT = "performance_report.txt"
LEARNING_FILE = "learning_memory.json"

cash_reserve_pct = 0.30
base_position_pct = 0.06
max_position_pct = 0.08
min_order_size = 1.00

max_open_positions = 4
max_trades_per_day = 10

take_profit_pct = 0.018
profit_lock_pct = 0.006
stop_loss_pct = -0.005
daily_loss_limit_pct = -0.02

min_entry_score = 4
min_hold_score = 2


def now_ny():
    return datetime.now(ny)


def log(msg):
    print(f"[{now_ny()}] {msg}")


def write_csv(file, headers, row):
    exists = Path(file).exists()
    with open(file, "a", newline="") as f:
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
    a = api.get_account()
    return float(a.cash), float(a.equity), float(a.last_equity)


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


def load_memory():
    if not Path(LEARNING_FILE).exists():
        return {"symbols": {}, "samples": []}

    try:
        with open(LEARNING_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"symbols": {}, "samples": []}


def save_memory(memory):
    with open(LEARNING_FILE, "w") as f:
        json.dump(memory, f, indent=2)


def update_learning_memory():
    memory = load_memory()

    for symbol in symbols:
        pos = get_position(symbol)
        if not pos:
            continue

        entry = float(pos.avg_entry_price)
        price = float(pos.current_price)

        if entry <= 0:
            continue

        gain = (price - entry) / entry
        technical = score_trend(symbol)

        stats = memory["symbols"].get(symbol, {
            "wins": 0,
            "losses": 0,
            "score_sum": 0,
            "observations": 0
        })

        if gain > 0.002:
            stats["wins"] += 1
            label = 1
        elif gain < -0.002:
            stats["losses"] += 1
            label = 0
        else:
            label = None

        stats["score_sum"] += technical
        stats["observations"] += 1

        memory["symbols"][symbol] = stats

        if label is not None:
            memory["samples"].append({
                "symbol": symbol,
                "score": technical,
                "gain": gain,
                "label": label
            })

    memory["samples"] = memory["samples"][-500:]
    save_memory(memory)


def learning_confidence(symbol):
    memory = load_memory()
    stats = memory["symbols"].get(symbol)

    if not stats:
        return 0.50

    wins = stats.get("wins", 0)
    losses = stats.get("losses", 0)
    total = wins + losses

    if total == 0:
        return 0.50

    return wins / total


def ml_confidence(symbol, technical_score):
    memory = load_memory()
    samples = memory.get("samples", [])

    if not ML_AVAILABLE or len(samples) < 20:
        return learning_confidence(symbol)

    try:
        X = np.array([[s["score"], s["gain"]] for s in samples])
        y = np.array([s["label"] for s in samples])

        if len(set(y)) < 2:
            return learning_confidence(symbol)

        model = LogisticRegression()
        model.fit(X, y)

        pred = model.predict_proba(np.array([[technical_score, 0]]))[0][1]
        return float(pred)

    except Exception:
        return learning_confidence(symbol)


def log_trade(action, symbol, qty=None, amount=None, price=None, reason="", strategy=""):
    write_csv(
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


def save_snapshot():
    cash, equity, last_equity = get_account()
    write_csv(
        SNAPSHOT_LOG,
        ["time", "cash", "equity", "last_equity"],
        {
            "time": str(now_ny()),
            "cash": cash,
            "equity": equity,
            "last_equity": last_equity
        }
    )


def hedge_mode_active():
    try:
        spy = api.get_bars("SPY", TimeFrame.Day, limit=30).df["close"]
        qqq = api.get_bars("QQQ", TimeFrame.Day, limit=30).df["close"]

        return spy.iloc[-1] < spy.tail(20).mean() or qqq.iloc[-1] < qqq.tail(20).mean()
    except Exception:
        return False


def market_regime():
    try:
        bars = api.get_bars("SPY", TimeFrame.Day, limit=60).df

        close = bars["close"]
        price = close.iloc[-1]
        ma20 = close.tail(20).mean()
        ma50 = close.tail(50).mean()

        if price > ma20 > ma50:
            return "bullish"
        if price < ma20 < ma50:
            return "bearish"
        return "neutral"

    except Exception:
        return "neutral"


def candidate_symbols(regime):
    if hedge_mode_active():
        log("SMART HEDGE MODE ACTIVE")
        return [
            "SGOV","BIL","SHV",
            "GLD","IAU","GDX","NEM","GOLD",
            "SLV","SIVR","AG","WPM","PPLT","PALL",
            "DBC","GSG","USO","UNG","UUP"
        ]

    if regime == "bullish":
        return [
            "QQQ","SPY","VTI","VOO","DIA","IWM",
            "NVDA","MSFT","AAPL","AMZN","GOOGL","META","TSLA",
            "XLK","XLY","JEPQ","SCHD"
        ]

    if regime == "bearish":
        return [
            "SGOV","BIL","SHV",
            "SCHD","VYM","JEPI","JEPQ",
            "O","STAG","MAIN",
            "KO","PEP","PG","JNJ","WMT","T",
            "GLD","IAU","UUP"
        ]

    return symbols


def choose_strategy(regime):
    if hedge_mode_active():
        return "hedge"
    if regime == "bullish":
        return "trend"
    if regime == "bearish":
        return "defensive"
    return "multi_asset"


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

    except Exception:
        return -999


def total_score(symbol):
    technical = score_trend(symbol)
    confidence = ml_confidence(symbol, technical)

    if technical < 0:
        return technical

    boost = 0

    if confidence >= 0.65:
        boost += 1
    if confidence >= 0.75:
        boost += 1
    if confidence <= 0.40:
        boost -= 1

    return technical + boost


def ranked_candidates(regime):
    candidates = candidate_symbols(regime)

    ranked = []
    for symbol in candidates:
        ranked.append((symbol, total_score(symbol)))

    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked


def submit_buy(symbol, amount, strategy):
    if amount < min_order_size:
        return False

    session = get_session()

    try:
        trade = api.get_latest_trade(symbol)
        price = float(trade.price)

        if session in ["pre_market", "after_hours"]:
            limit_price = round(price * 1.002, 2)

            api.submit_order(
                symbol=symbol,
                notional=round(amount, 2),
                side="buy",
                type="limit",
                limit_price=limit_price,
                time_in_force="day",
                extended_hours=True
            )

            log_trade("BUY", symbol, amount=amount, price=limit_price, reason="extended_entry", strategy=strategy)
            log(f"EXT BUY {symbol} ${round(amount, 2)}")

        elif session == "regular":
            api.submit_order(
                symbol=symbol,
                notional=round(amount, 2),
                side="buy",
                type="market",
                time_in_force="day"
            )

            log_trade("BUY", symbol, amount=amount, price=price, reason="regular_entry", strategy=strategy)
            log(f"BUY {symbol} ${round(amount, 2)}")

        else:
            return False

        return True

    except Exception as e:
        log(f"Buy failed {symbol}: {e}")
        return False


def submit_sell(symbol, qty, reason, strategy):
    if qty <= 0:
        return False

    session = get_session()

    try:
        trade = api.get_latest_trade(symbol)
        price = float(trade.price)

        if session in ["pre_market", "after_hours"]:
            limit_price = round(price * 0.998, 2)

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
            log(f"EXT SELL {symbol}")

        elif session == "regular":
            api.submit_order(
                symbol=symbol,
                qty=qty,
                side="sell",
                type="market",
                time_in_force="day"
            )

            log_trade("SELL", symbol, qty=qty, price=price, reason=reason, strategy=strategy)
            log(f"SELL {symbol} | {reason}")

        else:
            return False

        return True

    except Exception as e:
        log(f"Sell failed {symbol}: {e}")
        return False


def manage_positions(regime, strategy):
    ranked = ranked_candidates(regime)
    top_symbols = [s for s, sc in ranked[:max_open_positions] if sc >= min_entry_score]

    for symbol in symbols:
        pos = get_position(symbol)
        if not pos:
            continue

        qty = float(pos.qty)
        entry = float(pos.avg_entry_price)
        price = float(pos.current_price)

        if entry <= 0:
            continue

        gain = (price - entry) / entry
        sc = total_score(symbol)

        if gain >= take_profit_pct:
            submit_sell(symbol, qty, "take_profit", strategy)
            continue

        if gain >= profit_lock_pct and sc < min_hold_score:
            submit_sell(symbol, qty, "profit_lock", strategy)
            continue

        if gain <= stop_loss_pct:
            submit_sell(symbol, qty, "stop_loss", strategy)
            continue

        if gain < 0 and symbol not in top_symbols:
            submit_sell(symbol, qty, "rotation_loss", strategy)
            continue


def open_new_trades(regime, strategy):
    cash, equity, last_equity = get_account()

    if last_equity > 0:
        daily_change = (equity - last_equity) / last_equity
        if daily_change <= daily_loss_limit_pct:
            log("Daily loss limit hit.")
            return

    if todays_trade_count() >= max_trades_per_day:
        log("Max trades reached.")
        return

    open_positions = [s for s in symbols if get_position(s)]

    slots = max_open_positions - len(open_positions)
    if slots <= 0:
        return

    investable_cash = cash - (equity * cash_reserve_pct)

    if investable_cash < min_order_size:
        return

    ranked = ranked_candidates(regime)

    for symbol, sc in ranked:
        if slots <= 0:
            break

        if sc < min_entry_score:
            continue

        if get_position(symbol):
            continue

        confidence = ml_confidence(symbol, score_trend(symbol))

        position_pct = base_position_pct
        if confidence >= 0.70:
            position_pct += 0.01
        if confidence <= 0.40:
            position_pct -= 0.01

        position_pct = max(0.03, min(max_position_pct, position_pct))
        amount = min(equity * position_pct, investable_cash)

        if submit_buy(symbol, amount, strategy):
            slots -= 1
            investable_cash -= amount


def save_reports(session, regime, strategy):
    cash, equity, last_equity = get_account()

    save_snapshot()

    with open(RISK_REPORT, "w") as f:
        f.write("LEVEL 3A LEARNING BOT RISK REPORT\n")
        f.write("=================================\n")
        f.write(f"Time: {now_ny()}\n")
        f.write(f"Session: {session}\n")
        f.write(f"Regime: {regime}\n")
        f.write(f"Strategy: {strategy}\n")
        f.write(f"Cash: {cash}\n")
        f.write(f"Equity: {equity}\n")
        f.write(f"Trades today: {todays_trade_count()}\n")

    memory = load_memory()

    with open(PERFORMANCE_REPORT, "w") as f:
        f.write("LEVEL 3A LEARNING REPORT\n")
        f.write("========================\n")
        f.write(f"Time: {now_ny()}\n")
        f.write(f"ML available: {ML_AVAILABLE}\n")
        f.write(f"Learning samples: {len(memory.get('samples', []))}\n")
        f.write(f"Tracked symbols: {len(memory.get('symbols', {}))}\n")


def run_bot():
    log("----- LEVEL 3A ML-ASSISTED BOT START -----")

    session = get_session()
    regime = market_regime()
    strategy = choose_strategy(regime)

    log(f"Session: {session}")
    log(f"Regime: {regime}")
    log(f"Strategy: {strategy}")
    log(f"ML available: {ML_AVAILABLE}")

    update_learning_memory()

    if session == "closed":
        log("Market closed. Reports only.")
        save_reports(session, regime, strategy)
        return

    manage_positions(regime, strategy)
    open_new_trades(regime, strategy)

    update_learning_memory()
    save_reports(session, regime, strategy)

    log("----- LEVEL 3A ML-ASSISTED BOT END -----")


if __name__ == "__main__":
    run_bot()
