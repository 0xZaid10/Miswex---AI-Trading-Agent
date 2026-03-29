class Position:
    def __init__(self, price, size, strat, symbol, order_id=None):
        # ===== ENTRY INFO =====
        self.entry = price
        self.size = size
        self.symbol = symbol
        self.strat = strat

        # ===== PRICE TRACKING =====
        self.max = price
        self.max_dd_pct = 0.0   # track max drawdown %

        # ===== LIFECYCLE =====
        self.age = 0            # candles held
        self.scales = 0

        # ===== WEEX TRACKING =====
        self.order_id = order_id        # open order id
        self.close_order_id = None      # close order id
        self.exit = None

        # ===== GEMINI ANALYSIS GATE =====
        # Ensures Gemini ANALYSIS is called only once per 5m candle
        self.last_gemini_5m_candle = -1

        # ===== REENTRY / AI METADATA (OPTIONAL, SAFE DEFAULTS) =====
        self.entry_features = None
        self.entry_score = None
        self.last_5m_score = None
        self.reentry_state = None
        self.reentry_action = None
        self.exit_mode = "NORMAL"
        self.tf = None
        self.entry_candle_idx = None

    # CALL THIS ONLY ON CANDLE CLOSE (1m in your system)
    def update(self, price):
        # Update max favorable price
        if price > self.max:
            self.max = price

        # Update max drawdown percentage (relative to entry)
        dd = (self.max - price) / self.entry
        self.max_dd_pct = max(self.max_dd_pct, dd)

        self.age += 1

    def close(self, price, close_order_id=None):
        self.exit = price
        self.close_order_id = close_order_id
