import random

def mutate(g):

    if random.random()<0.6: g.entry*=random.uniform(0.4,1.6)
    if random.random()<0.5: g.tp*=random.uniform(0.5,2)
    if random.random()<0.5: g.sl*=random.uniform(0.5,2)
    if random.random()<0.4: g.trail*=random.uniform(0.5,2)
    if random.random()<0.3: g.scale*=random.uniform(0.5,2)

    # MICRO MUTATIONS
    if random.random()<0.5:
        g.use_micro ^= 1      # toggle on/off

    if random.random()<0.5:
        g.micro_w += random.uniform(-0.5,0.5)

    # chaos
    if random.random()<0.05:
        g.tp*=random.uniform(3,10)
        g.btc_w=random.uniform(-5,5)

    return g
