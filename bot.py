import os
import alpaca_trade_api as tradeapi

API_KEY = os.getenv("AKDVTJLITHW7LYMQHBA5LJC4NF")
SECRET_KEY = os.getenv("6WChiDsTgdGzQ82R4EfAGDFWDnUCYAVavdZ5Hp4RRdm8")
BASE_URL = "https://api.alpaca.markets"

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL)

basket = {
    "SGOV": 0.30,
    "SCHD": 0.25,
    "JEPI": 0.20,
    "O": 0.15,
    "VTI": 0.10
}

total_budget = 10

account = api.get_account()
cash = float(account.cash)

if not account.trading_blocked and cash >= total_budget:
    for symbol, weight in basket.items():
        dollars = round(total_budget * weight, 2)

        api.submit_order(
            symbol=symbol,
            notional=dollars,
            side="buy",
            type="market",
            time_in_force="day"
        )

    print("Trades executed")
else:
    print("Not ready")