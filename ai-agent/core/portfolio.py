class Portfolio:

    def __init__(self):
        self.balance = 1000.0   # starting capital

        self.open = []
        self.closed = []

        self.total_pnl = 0
        self.wins = 0
        self.losses = 0

    def can_open(self, strat):

        # ENGINE RULE: max 4 open positions
        if len(self.open) >= 4:
            return False

        # block same strategy duplicate
        for p in self.open:
            if p.strat == strat:
                return False

        return True

    def register(self, pos):
        self.open.append(pos)

    def close(self, pos):

        self.open.remove(pos)
        self.closed.append(pos)

        trade_pnl = (pos.exit - pos.entry) / pos.entry
        pnl_value = trade_pnl * self.balance

        self.balance += pnl_value
        self.total_pnl += trade_pnl

        if trade_pnl > 0:
            self.wins += 1
        else:
            self.losses += 1
