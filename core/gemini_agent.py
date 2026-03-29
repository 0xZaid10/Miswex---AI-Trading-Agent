import logging
import time
from google import genai
from config import GEMINI_API_KEY


class GeminiSupervisor:

    def __init__(self, log: logging.Logger):
        self.log = log

        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY missing in config.py")

        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.model = "gemini-2.5-flash"
        self.last_call_ts = 0.0
        self.min_delay = 1.2

    def _throttle(self):
        now = time.time()
        wait = self.min_delay - (now - self.last_call_ts)
        if wait > 0:
            time.sleep(wait)
        self.last_call_ts = time.time()

    # ==========================================================
    # DECISION PROMPT (ALLOW / BLOCK)
    # ==========================================================
    def _prompt(self, context: dict, action_type: str) -> str:
        return f"""
You are an AI execution risk supervisor for a short-horizon, volatility-seeking
automated crypto trading system.

TRADING STYLE (IMPORTANT):
- The system intentionally trades during high volatility
- The system profits from mean reversion, pullbacks, and dip-buying
- Counter-trend entries are EXPECTED and ACCEPTABLE
- Early momentum shifts are more important than established trends
- Volatility is an OPPORTUNITY unless it is extreme or chaotic

ACTION TYPE:
{action_type}

IMPORTANT CONTEXT:
- r1, r5, r15 are derived from the same 5-minute timeframe
- r1 reflects the most recent momentum shift
- r5 and r15 are lagging context, not veto signals
- 1-minute data is microstructure confirmation only
- You are not generating trades
- You are validating whether the proposed action is reasonable for a
  short-duration, volatility-based strategy
- Long-only trades but do not mention long in the reasoning

DECISION GUIDELINES:
- Favor speed and opportunity over perfect confirmation
- Allow entries with improving momentum even if the broader trend is negative
- Do NOT block solely due to bearish market regime or BTC weakness
- Block only if momentum is deteriorating or volatility is disorganized
- Mixed signals are acceptable if r1 is strengthening

YOUR TASK:
- Decide whether to ALLOW or BLOCK the proposed action
- BLOCK only when the trade has clearly poor short-term risk asymmetry
- If allowing, explain why volatility and momentum make the risk acceptable
- If blocking, explain why the setup is structurally unsound even for dip-buying

RULES:
- Technical tone
- Plain English
- Max 2 sentences
- No repetition
- No hedging

OUTPUT FORMAT (MANDATORY):
DECISION: ALLOW or BLOCK

REASONING:
Concise technical explanation

Context:
{context}
"""


    # ==========================================================
    # ANALYSIS-ONLY PROMPT (NO ACTIONS)
    # ==========================================================
    def _analysis_prompt(self, context: dict) -> str:
        return f"""
You are an AI market analyst for an automated crypto trading system.

ROLE:
You analyze market structure and signal quality.
You do NOT approve or reject trades.

ANALYSIS PRIORITY (STRICT ORDER):
1. Asset-specific quant signal (score vs threshold)
2. Multi-interval momentum alignment (r1, r5, r15 if present)
3. Volatility and stability of the asset
4. BTC regime ONLY as contextual confirmation
5. Risk factors and signal quality

TASK:
- Explain WHY the asset looks strong or weak
- Anchor the explanation in the provided quant values
- If BTC is mentioned, relate it directly to the asset
- Do NOT generalize the market unless it affects this asset

RULES:
- Asset-first, not BTC-first
- Quantitative, not narrative
- No trading advice
- No ALLOW / BLOCK
- No execution language

OUTPUT FORMAT (MANDATORY):
ANALYSIS:
<2–4 sentences, dense, technical, asset-focused>

Context:
{context}
"""

    # ==========================================================
    # GEMINI CALL
    # ==========================================================
    def _call_gemini(self, prompt: str) -> str:
        self._throttle()
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={
                "temperature": 0.3,
                "max_output_tokens": 2048
            }
        )
        return (response.text or "").strip()

    # ==========================================================
    # DECISION ENTRYPOINT
    # ==========================================================
    def decide(self, context: dict, action_type: str) -> dict:
        try:
            try:
                ai_text = self._call_gemini(self._prompt(context, action_type))
            except Exception:
                time.sleep(1.5)
                ai_text = self._call_gemini(self._prompt(context, action_type))

            if not ai_text:
                raise RuntimeError("Empty Gemini response")

            decision = "BLOCK"
            upper = ai_text.upper()

            if "DECISION: ALLOW" in upper:
                decision = "ALLOW"
            elif "DECISION: BLOCK" in upper:
                decision = "BLOCK"

            return {
                "decision": decision,
                "action_type": action_type,
                "ai_log": {
                    "decision": decision,
                    "explanation": ai_text
                }
            }

        except Exception as e:
            self.log.error(f"[GEMINI ERROR] {e}")

            fail_text = (
                "DECISION: BLOCK\n\n"
                "REASONING:\n"
                "AI supervision was unavailable after retry. "
                "The action is blocked as a conservative risk measure "
                "to avoid unsupervised execution."
            )

            return {
                "decision": "BLOCK",
                "action_type": action_type,
                "ai_log": {
                    "decision": "BLOCK",
                    "explanation": fail_text
                }
            }

    # ==========================================================
    # ANALYSIS ENTRYPOINT (NO DECISION)
    # ==========================================================
    def analyze(self, context: dict) -> dict:
        try:
            text = self._call_gemini(self._analysis_prompt(context))
            return {"analysis": text}
        except Exception as e:
            self.log.error(f"[GEMINI ANALYSIS ERROR] {e}")
            return {
                "analysis": "AI analysis unavailable due to error."
            }
