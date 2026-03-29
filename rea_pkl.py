import pickle
from pprint import pprint

FILES = [
    "strategies/SOL_5m.pkl",
    "strategies/DOGE_5m.pkl",
]

for file in FILES:
    print(f"\n===== Loading {file} =====")

    with open(file, "rb") as f:
        data = pickle.load(f)

    print("Type:", type(data))
    print("Length:", len(data))

    for i, x in enumerate(data):
        print(f"\n--- STRATEGY {i} ---")
        pprint(x.__dict__)
