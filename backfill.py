# backfill.py
# One-time backfill for missing CLOSE logs after AI update

from core.ai_logger import push_ai_log

BACKFILL_DECISION = (
    "CLOSE_HARD_STOP | "
    "Backfilled log: close-side AI logging was disabled after AI update; "
    "fix applied and close/open logs now emitted normally"
)

BACKFILLS = [
    "710966605399458332",
    "710988974163755548"
    ]

def main():
    for order_id in BACKFILLS:
        push_ai_log(
            stage="DECISION",
            genome=None,        # no genome for backfill
            X=[],               # no feature window
            btc=[],             # no btc window
            micro=[],           # no micro window
            score=-1.0,
            decision=BACKFILL_DECISION,
            order_id=order_id,
            meta={
                "backfill": True,
                "cause": "ai_update_logging_gap",
                "status": "fixed"
            }
        )
        print(f"Backfilled CLOSE log for order_id={order_id}")

if __name__ == "__main__":
    main()
