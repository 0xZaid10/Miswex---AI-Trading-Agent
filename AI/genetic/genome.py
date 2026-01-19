import random

FEATURE_COUNT = 7   # MUST MATCH alt feature count

class Genome:

    def __init__(self):

        self.f_idx = random.sample(
            range(FEATURE_COUNT),
            k=random.randint(2, FEATURE_COUNT)
        )

        self.entry = random.uniform(0,1)
        self.tp = random.uniform(0.5,5)
        self.sl = random.uniform(0.5,5)
        self.trail = random.uniform(0.1,2)

        self.scale = random.uniform(0.1,2)
        self.max_scales = random.randint(1,3)
        self.min_hold = random.randint(1,10)

        self.btc_w = random.uniform(-3,3)

        self.base_w = random.uniform(0,2)

        # MICRO SIGNAL
        self.use_micro = random.choice([0,1])
        self.micro_w = random.uniform(-2,2)

        self.pref_reg = random.choice(["trend","chop","high_vol"])
        self.reg_conf = random.uniform(0,1)

    def clone(self):
        g = Genome()
        g.__dict__ = self.__dict__.copy()
        return g
