class Position:
    def __init__(self, price, size, strat, symbol):
        self.entry = price
        self.size = size
        self.symbol = symbol
        self.max = price
        self.age = 0
        self.scales = 0
        self.strat = strat

        self.exit = None  # NEW

    def update(self, price):
        self.max = max(self.max, price)
        self.age += 1

    def close(self, price):   # NEW
        self.exit = price
