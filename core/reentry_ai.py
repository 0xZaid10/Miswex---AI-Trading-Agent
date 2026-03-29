import json
import os
import random
from collections import defaultdict

# ==================================================
# ENTRY AI CONSTANTS (NEW)
# ==================================================
ENTRY_ACTIONS = ["WAIT", "ENTER", "ABORT"]
ENTRY_ALPHA = 0.08

# ==================================================
# REENTRY AI CONSTANTS (EXISTING)
# ==================================================
ACTIONS = [0, 1, 2, 3, 4, "SKIP"]

ALPHA = 0.15
EARLY_WEIGHT = 0.006     # reward candle 2 & 3 only
DD_WEIGHT = 0.8
TIME_WEIGHT = 0.001

MEM_PATH = "data/reentry_memory.json"
os.makedirs("data", exist_ok=True)


class ReentryAI:

    def __init__(self, logger):
        self.log = logger

        # --------------------------
        # REENTRY MEMORY
        # --------------------------
        self.Q = defaultdict(lambda: {a: 0.0 for a in ACTIONS})
        self.trades = 0

        # --------------------------
        # ENTRY AI WEIGHTS (NEW)
        # --------------------------
        self.entry_weights = {
            "rsi": 0.9,
            "dump": -1.2,
            "stability": 0.7,
            "time": 0.25
        }

        self._load()

    # ==================================================
    # LOAD / SAVE
    # ==================================================
    def _load(self):
        if not os.path.exists(MEM_PATH):
            return

        try:
            with open(MEM_PATH) as f:
                raw = json.load(f)

            self.trades = raw.get("trades", 0)

            for k, v in raw.get("Q", {}).items():
                state = tuple(json.loads(k))
                self.Q[state] = v

            # -------- ENTRY AI LOAD (NEW)
            self.entry_weights = raw.get(
                "entry_weights",
                self.entry_weights
            )

            self.log.info(
                f"[REENTRY_AI] memory loaded (trades={self.trades})"
            )

        except Exception as e:
            self.log.error(f"[REENTRY_AI] memory load failed: {e}")

    def _save(self):
        try:
            with open(MEM_PATH, "w") as f:
                json.dump(
                    {
                        "trades": self.trades,
                        "Q": {json.dumps(k): v for k, v in self.Q.items()},
                        # -------- ENTRY AI SAVE (NEW)
                        "entry_weights": self.entry_weights,
                    },
                    f,
                    indent=2
                )
        except Exception as e:
            self.log.error(f"[REENTRY_AI] memory save failed: {e}")

    # ==================================================
    # ENTRY AI LOGIC (NEW)
    # ==================================================
    def rsi_bonus(self, rsi):
        if rsi is None:
            return 0.0
        if rsi <= 20: return 2.2
        if rsi <= 25: return 1.8
        if rsi <= 30: return 1.4
        if rsi <= 35: return 1.0
        if rsi <= 40: return 0.5
        return 0.0

    def entry_decide(self, features):
        """
        Decide WAIT / ENTER / ABORT
        Called every candle.
        """
        rsi = features["rsi"]
        dump = features["dump_speed"]
        stab = features["stability"]
        t = features["minutes_waited"]

        score = (
            self.entry_weights["rsi"] * self.rsi_bonus(rsi)
            + self.entry_weights["dump"] * dump
            + self.entry_weights["stability"] * stab
            + self.entry_weights["time"] * t
        )

        if score > 1.0:
            decision = "ENTER"
        elif score < -1.2:
            decision = "ABORT"
        else:
            decision = "WAIT"

        self.log.info(
            "[ENTRY_AI] "
            f"rsi={None if rsi is None else round(rsi,1)} "
            f"dump={round(dump,4)} "
            f"stab={round(stab,2)} "
            f"t={t} "
            f"score={round(score,3)} "
            f"→ {decision}"
        )

        return decision, score

    def reward_entry(self, features, pnl, max_dd):
        """
        Learn ONLY after trade closes.
        """
        if features is None:
            return

        target = pnl - max_dd * 0.5

        for k in self.entry_weights:
            old = self.entry_weights[k]
            self.entry_weights[k] += ENTRY_ALPHA * target
            self.entry_weights[k] = max(-3, min(3, self.entry_weights[k]))

            self.log.info(
                f"[ENTRY_LEARN] {k}: {round(old,3)} → {round(self.entry_weights[k],3)}"
            )

        self._save()

    # ==================================================
    # REENTRY AI (EXISTING)
    # ==================================================
    def choose(self, state):
        """
        Decide WHEN (or SKIP) reentry.
        Does NOT decide WHETHER score is valid.
        """
        epsilon = max(0.05, 1 - self.trades / 25)

        if random.random() < epsilon:
            action = random.choice(ACTIONS)
        else:
            qvals = self.Q[state]
            action = max(qvals, key=qvals.get)

        self.log.debug(
            f"[REENTRY_DECISION] state={state} "
            f"chosen={action} Q={self.Q[state]}"
        )

        return action

    def reward(
        self,
        state,
        action,
        pnl_pct,
        max_dd_pct,
        held_candles
    ):
        """
        Reward ONLY reflects outcome.
        No score logic, no hard rules.
        """
        if action is None:
            return

        R_pnl = pnl_pct

        # reward ONLY candle 2 & 3, and only if profitable
        if isinstance(action, int) and pnl_pct > 0 and action in (2, 3):
            R_early = EARLY_WEIGHT
        else:
            R_early = 0

        R_dd = -DD_WEIGHT * max_dd_pct
        R_time = -TIME_WEIGHT * held_candles

        R = R_pnl + R_early + R_dd + R_time

        old = self.Q[state][action]
        self.Q[state][action] += ALPHA * (R - old)

        self.trades += 1

        self.log.info(
            "[REENTRY_REWARD] "
            f"action={action} "
            f"pnl={round(pnl_pct * 100, 2)}% "
            f"dd={round(max_dd_pct * 100, 2)}% "
            f"held={held_candles} "
            f"R={round(R, 5)} "
            f"Q:{round(old, 4)}→{round(self.Q[state][action], 4)}"
        )

        if self.trades % 20 == 0:
            self._save()
