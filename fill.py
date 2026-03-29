from core.ai_logger import upload_gemini_log
from core.gemini_agent import GeminiSupervisor
from utils.logger import setup_logger

log = setup_logger()
gemini = GeminiSupervisor(log)

close_order_id = "716181522452840476"  # ✅ real WEEX order id

exit_context = {
    "symbol": "DOGEUSDT",
    "exit_reason": "SIGNAL_DECAY",
    "exit_mode": "NORMAL",
    "exit_note": (
        "Momentum weakened and short-term signal strength "
        "fell below continuation threshold"
    ),
    "order_id": close_order_id
}

analysis_text = gemini.analyze(exit_context)["analysis"]

upload_gemini_log(
    action_type="EXIT",
    decision="ALLOW",
    explanation=analysis_text,
    order_id=close_order_id
)

print("✅ EXIT Gemini log backfilled (strategy-based) for:", close_order_id)
