class Position:
    def __init__(self, price, size, strat, symbol, order_id=None):
        self.entry = price
        self.size = size
        self.symbol = symbol
        self.max = price
        self.age = 0
        self.scales = 0
        self.strat = strat

        # WEEX tracking
        self.order_id = order_id        # open order id
        self.close_order_id = None      # close order id

        self.exit = None

    # CALL THIS ONLY ON CANDLE CLOSE
    def update(self, price):
        self.max = max(self.max, price)
        self.age += 1

    def close(self, price, close_order_id=None):
        self.exit = price
        self.close_order_id = close_order_id
