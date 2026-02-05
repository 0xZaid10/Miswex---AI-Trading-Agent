class Position:
    def __init__(self, price, size, strat, symbol, order_id=None):
        self.entry = price
        self.size = size
        self.symbol = symbol

        # Price tracking
        self.max = price
        self.max_dd_pct = 0.0   # ✅ FIX: track max drawdown %

        # Lifecycle
        self.age = 0
        self.scales = 0
        self.strat = strat

        # WEEX tracking
        self.order_id = order_id        # open order id
        self.close_order_id = None      # close order id

        self.exit = None

    # CALL THIS ONLY ON CANDLE CLOSE
    def update(self, price):
        # Update max favorable price
        if price > self.max:
            self.max = price

        # Update max drawdown percentage
        dd = (self.max - price) / self.entry
        self.max_dd_pct = max(self.max_dd_pct, dd)

        self.age += 1

    def close(self, price, close_order_id=None):
        self.exit = price
        self.close_order_id = close_order_id
