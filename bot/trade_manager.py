
def place_trade(api, symboltoken, signal):

    if signal["signal"] != "BUY":
        print("No trade")
        return

    orderparams = {
        "variety": "NORMAL",
        "tradingsymbol": "NATURALGAS",
        "symboltoken": symboltoken,
        "transactiontype": "BUY",
        "exchange": "MCX",
        "ordertype": "MARKET",
        "producttype": "INTRADAY",
        "duration": "DAY",
        "quantity": 1
    }

    order = api.placeOrder(orderparams)

    print(order)

