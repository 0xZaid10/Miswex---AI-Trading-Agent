import os
import re

LOG_DIR = "./logs"
OUT_DIR = "./trades"

os.makedirs(OUT_DIR, exist_ok=True)

DATE_RE = re.compile(r"bot_(\d{8})")

def extract_date(filename):
    m = DATE_RE.search(filename)
    return m.group(1) if m else "00000000"

# Accept ANY file starting with bot_
files = sorted(
    [f for f in os.listdir(LOG_DIR) if f.startswith("bot_")],
    key=extract_date
)

print(f"📂 Files detected: {len(files)}")

trade_active = False
trade_lines = []
trade_id = 0

open_hits = 0
close_hits = 0

for file in files:
    path = os.path.join(LOG_DIR, file)

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line_stripped = line.strip()

            # ---- START ----
            if "PLACE LONG" in line_stripped:
                open_hits += 1
                trade_active = True
                trade_lines = [line]
                continue

            # ---- INSIDE TRADE ----
            if trade_active:
                trade_lines.append(line)

                # ---- END ----
                if "CLOSE LONG" in line_stripped:
                    close_hits += 1
                    trade_id += 1

                    out_file = os.path.join(
                        OUT_DIR, f"trade_{trade_id:04d}.txt"
                    )

                    with open(out_file, "w", encoding="utf-8") as out:
                        out.writelines(trade_lines)

                    trade_active = False
                    trade_lines = []

print("\n📊 DEBUG SUMMARY")
print(f"OPEN hits  : {open_hits}")
print(f"CLOSE hits : {close_hits}")
print(f"TRADES OUT : {trade_id}")
