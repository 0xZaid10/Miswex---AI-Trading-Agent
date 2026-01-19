import pickle
import os

DIR = "checkpoints"
os.makedirs(DIR, exist_ok=True)

def save(pop, name):
    path = f"{DIR}/{name}.pkl"
    with open(path,"wb") as f:
        pickle.dump(pop,f)
    print("CHECKPOINT:", path)

def load(path):
    with open(path,"rb") as f:
        return pickle.load(f)
