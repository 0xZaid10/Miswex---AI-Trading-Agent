# core/ai_logger.py

from core.weex_api import upload_ai_log

GEMINI_MODEL = "Gemini-2.5-Flash"


def upload_gemini_log(
    *,
    action_type: str,     # ENTRY | EXIT | ANALYSIS
    decision: str,        # ALLOW | BLOCK | OBSERVE
    explanation: str,
    order_id: str | None
):
    """
    Upload a Gemini AI decision log to WEEX.
    This is the ONLY AI log used in the system.
    """

    return upload_ai_log(
        order_id=order_id,                 # None if no execution
        stage=f"GEMINI_{action_type}_DECISION",
        model=GEMINI_MODEL,
        input_data={},                     # intentionally empty
        output_data={
            "decision": decision
        },
        explanation=explanation[:1000]     # WEEX limit
    )
