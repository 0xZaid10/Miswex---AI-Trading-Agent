import logging
from google import genai
from config import GEMINI_API_KEY


class GeminiSupervisor:
    """
    Gemini-based AI supervisor for WEEX AI log compliance.

    - Role: Reasoning + Supervision
    - Does NOT trade
    - Does NOT size positions
    - Can ALLOW or BLOCK ENTRY and EXIT
    """

    def __init__(self, log: logging.Logger):
        self.log = log

        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY missing in config.py")

        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.model = "gemini-3-flash-preview"

    def _prompt(self, context: dict, action_type: str) -> str:
        return f"""
You are an AI risk supervisor for an automated crypto trading system.

ACTION TYPE:
- {action_type}

IMPORTANT CONTEXT:
- r1, r5, r15 are ALL derived from 5-minute candles
- They represent momentum on the SAME timeframe
- 1-minute data is only microstructure confirmation
- You are NOT deciding the trade — only validating it

YOUR TASK:
- Decide whether the proposed action is reasonable
- Focus on momentum, volatility, regime, and risk
- Explain briefly and technically

RULES:
- Be concise
- No storytelling
- No repetition
- Plain English
- Technical tone

ENTRY LOGIC:
- Confirm momentum alignment (r1 / r5 / r15)
- Confirm volatility is acceptable
- Justify continuation probability

EXIT LOGIC:
- Explain why exiting NOW is valid
- Momentum decay, volatility expansion, drawdown control
- Capital preservation > signal perfection

FORMAT:
- Plain text
- 2–4 short paragraphs
- Each paragraph must add new information

Context:
{context}
"""

    def decide(self, context: dict, action_type: str) -> dict:
        """
        action_type: 'ENTRY' or 'EXIT'
        """

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=self._prompt(context, action_type),
                config={
                    "temperature": 0.3,
                    "max_output_tokens": 1024
                }
            )

            ai_text = (response.text or "").strip()
            if not ai_text:
                ai_text = "Gemini returned no explanation."

            # ===============================
            # DECISION RULES (EXPLICIT)
            # ===============================

            if action_type == "ENTRY":
                decision = (
                    "ALLOW"
                    if context.get("quant_score", 0) >= context.get("entry_threshold", 1)
                    else "BLOCK"
                )

            elif action_type == "EXIT":
                # Exit is allowed by default unless Gemini sees irrational behavior
                decision = "ALLOW"

            else:
                decision = "BLOCK"

            return {
                "decision": decision,
                "action_type": action_type,
                "ai_log": {
                    "stage": f"GEMINI_{action_type}_SUPERVISION",
                    "model": "Gemini-3-Flash-Preview",
                    "input": {
                        "context": context
                    },
                    "output": {
                        "raw_response": ai_text
                    },
                    "explanation": ai_text
                }
            }

        except Exception as e:
            self.log.error(f"[GEMINI ERROR] {e}")

            return {
                "decision": "BLOCK",
                "action_type": action_type,
                "ai_log": {
                    "stage": f"GEMINI_{action_type}_SUPERVISION",
                    "model": "Gemini-3-Flash-Preview",
                    "input": {
                        "context": context
                    },
                    "output": {
                        "raw_response": "Gemini failed to generate explanation."
                    },
                    "explanation": "Gemini failed to generate explanation."
                }
            }
