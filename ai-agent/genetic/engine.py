from .genome import Genome
from .mutation import mutate
from backtest.executor import run
from backtest.metrics import fitness
import random
from multiprocessing import Pool

CORES = 3   # HARD LOCK (VPS SAFE)


# ---------- MULTI PROCESS WORKER ----------

def eval_genome(args):
    g, df, X, btcX, microX, ga = args

    cap, tr = run(df, X, btcX, microX, g)
    fit = fitness(cap, tr)

    # ---- VALIDATION PRESSURE ----
    val_cap, val_trades = ga.eval_one(
        g,
        ga.val_df,
        ga.val_X,
        ga.val_B,
        ga.val_micro
    )

    # ---- HARD VALIDATION RULE ----
    if val_trades < 10:
        fit *= 0.1   # brutal penalty

    fit = fit * (val_cap ** 2)

    return (fit, g)


# ---------- GA ENGINE ----------

class GA:

    def __init__(self, n):
        self.pop = [Genome() for _ in range(n)]

        # STORE VALIDATION DATA
        self.val_df = None
        self.val_X = None
        self.val_B = None
        self.val_micro = None


    # 🔁 UPDATED: now returns trade COUNT
    def eval_one(self, g, df, X, btcX, microX):
        cap, trades = run(df, X, btcX, microX, g)
        return cap, len(trades)


    def evolve(self, df, X, btcX, microX,
               val_df, val_X, val_B, val_micro):

        # STORE VALIDATION DATA
        self.val_df = val_df
        self.val_X = val_X
        self.val_B = val_B
        self.val_micro = val_micro

        # PREPARE JOBS
        jobs = [(g, df, X, btcX, microX, self) for g in self.pop]

        # MULTI CORE EXECUTION
        with Pool(CORES) as p:
            scored = p.map(eval_genome, jobs)

        # SORT BY FITNESS
        scored.sort(reverse=True, key=lambda x: x[0])

        elite = scored[:10]   # TOP KILLERS

        new_pop = []

        # ELITE PRESERVATION
        for _, g in elite:
            new_pop.append(g.clone())
            new_pop.append(mutate(g.clone()))

        # BREED REST
        while len(new_pop) < len(self.pop):
            parent = random.choice(elite)[1]
            new_pop.append(mutate(parent.clone()))

        # DIVERSITY INJECTION
        for _ in range(30):
            new_pop.append(Genome())

        # TRIM TO POP SIZE
        self.pop = new_pop[:len(self.pop)]

        return elite
