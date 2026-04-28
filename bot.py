import os
import alpaca_trade_api as tradeapi

API_KEY = os.getenv("APCA_API_KEY_ID")
SECRET_KEY = os.getenv("APCA_API_SECRET_KEY")
BASE_URL = "https://api.alpaca.markets"

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL)

total_budget = 10

basket = {
    "SGOV": 0.25,
    "SCHD": 0.25,
    "JEPI": 0.20,
    "O": 0.15,
    "VTI": 0.15
}

profit_target = 1.03  # sell if position is up 3%
dip_buy_level = 0.98  # buy if price is below 2% from recent high logic fallback

account = api.get_account()
cash = float(account.cash)

print("Account status:", account.status)
print("Cash:", cash)

if account.trading_blocked:
    print("Trading blocked.")
    exit()

# Profit-taking logic
positions = api.list_positions()

for position in positions:
    symbol = position.symbol
    avg_price = float(position.avg_entry_price)
    current_price = float(position.current_price)
    qty = abs(float(position.qty))

    if current_price >= avg_price * profit_target:
        api.submit_order(
            symbol=symbol,
            qty=qty,
            side="sell",
            type="market",
            time_in_force="day"
        )
        print(f"Sold {symbol} for profit at ${current_price}")

# Buying logic
if cash >= total_budget:
    for symbol, weight in basket.items():
        dollars = round(total_budget * weight, 2)

        if dollars >= 1:
            api.submit_order(
                symbol=symbol,
                notional=dollars,
                side="buy",
                type="market",
                time_in_force="day"
            )
            print(f"Bought ${dollars} of {symbol}")
else:
    print("Not enough cash to buy.")

print("Bot finished.")
