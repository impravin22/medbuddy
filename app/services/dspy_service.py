"""DSPy service — typed signatures and LM singletons for medication intelligence.

All Gemini LLM calls go through this module. Never call Gemini directly
from handlers or endpoints.

Patterns:
- configure_dspy() is idempotent — call at start of any function using DSPy
- LM singletons: get_dspy_fast_lm(), get_dspy_creative_lm()
- Use dspy.context(lm=...) for per-call LM overrides
- Module instances are singletons, never per-request
"""

from functools import lru_cache
from typing import Literal

import dspy

from app.config import settings

# ---------------------------------------------------------------------------
# LM Singletons
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_dspy_fast_lm() -> dspy.LM:
    """Fast LM for real-time pipeline (webhook latency-sensitive)."""
    return dspy.LM(
        f"gemini/{settings.GOOGLE_AI_FAST_MODEL}",
        api_key=settings.GOOGLE_API_KEY,
        temperature=0.2,
        max_tokens=512,
    )


@lru_cache(maxsize=1)
def get_dspy_creative_lm() -> dspy.LM:
    """Quality LM for medication explanations (accuracy over speed)."""
    return dspy.LM(
        f"gemini/{settings.GOOGLE_AI_DEFAULT_MODEL}",
        api_key=settings.GOOGLE_API_KEY,
        temperature=0.4,
        max_tokens=2048,
    )


_configured = False


def configure_dspy() -> None:
    """Idempotent DSPy configuration. Safe to call at the start of any function."""
    global _configured
    if _configured:
        return
    dspy.configure(lm=get_dspy_fast_lm())
    _configured = True


# ---------------------------------------------------------------------------
# DSPy Signatures
# ---------------------------------------------------------------------------


class MedicationExplanation(dspy.Signature):
    """Explain a medication in plain 繁體中文 at primary-school reading level.

    Rules:
    - NEVER give specific medical advice
    - NEVER recommend dosage changes or catching up missed doses
    - ALWAYS include "請詢問您的醫生" (please ask your doctor)
    - Use warm, simple language suitable for elderly patients
    - Maximum 4 sentences for the explanation
    """

    medication_name: str = dspy.InputField(desc="Drug name (English, Chinese, or mixed)")
    dosage_info: str = dspy.InputField(
        desc="Dosage and frequency from prescription, or 'unknown' if not provided"
    )
    patient_medications: list[str] = dspy.InputField(
        desc="List of user's other current medication names for context"
    )

    explanation: str = dspy.OutputField(
        desc="2-4 sentences in 繁體中文 explaining what this medication does, warm tone"
    )
    warnings: list[str] = dspy.OutputField(
        desc="Max 3 key warnings in 繁體中文, each under 20 characters"
    )
    take_with_food: bool = dspy.OutputField(
        desc="Whether this medication should be taken with food"
    )


class InteractionExplanation(dspy.Signature):
    """Explain a drug interaction in plain 繁體中文.

    The interaction data comes from RxNorm (authoritative source).
    Your job is ONLY to explain it simply — do NOT add medical judgement.
    ALWAYS include "請在下次看醫生時告訴他" (please tell your doctor next visit).
    """

    drug_a: str = dspy.InputField(desc="First drug name")
    drug_b: str = dspy.InputField(desc="Second drug name")
    interaction_data: str = dspy.InputField(
        desc="Raw interaction data from RxNorm API (JSON string)"
    )

    explanation: str = dspy.OutputField(
        desc="Plain-language explanation in 繁體中文, 2-3 sentences"
    )
    severity: Literal["none", "mild", "moderate", "severe"] = dspy.OutputField(
        desc="Interaction severity level"
    )
    action_needed: str = dspy.OutputField(
        desc="What the patient should do, in 繁體中文 (always includes telling their doctor)"
    )


class AdherenceCheckIn(dspy.Signature):
    """Parse a user's response to a daily medication check-in.

    Be warm and non-judgmental. NEVER scold for missed doses.
    NEVER recommend catching up a missed dose — this can be dangerous.
    """

    user_response: str = dspy.InputField(
        desc="User's voice/text response in Chinese about their medication today"
    )
    scheduled_medications: list[str] = dspy.InputField(
        desc="List of medication names the user should have taken today"
    )

    taken: list[str] = dspy.OutputField(desc="Medications confirmed as taken")
    missed: list[str] = dspy.OutputField(desc="Medications not yet taken or confirmed missed")
    follow_up: str = dspy.OutputField(
        desc="Warm, non-judgmental follow-up message in 繁體中文, 1-2 sentences"
    )


class ConversationResponse(dspy.Signature):
    """Respond to a general medication-related question in 繁體中文.

    Rules:
    - Answer at primary-school reading level
    - NEVER give specific medical advice
    - ALWAYS defer to the user's doctor for decisions
    - If the question is outside medication topics, gently redirect
    """

    user_message: str = dspy.InputField(desc="User's message in Chinese")
    medication_context: list[str] = dspy.InputField(desc="User's current medications for context")
    conversation_summary: str = dspy.InputField(
        desc="Brief summary of recent conversation, or 'none' if first message"
    )

    response: str = dspy.OutputField(desc="Helpful response in 繁體中文, 2-4 sentences, warm tone")
    intent: Literal[
        "medication_query",
        "interaction_query",
        "adherence_update",
        "greeting",
        "off_topic",
        "unknown",
    ] = dspy.OutputField(desc="Detected intent of the user's message")
    mentioned_drug: str = dspy.OutputField(
        desc="Drug name mentioned in the message, or 'none' if no drug mentioned"
    )


# ---------------------------------------------------------------------------
# Module Singletons (created once, reused across requests)
# ---------------------------------------------------------------------------

_medication_explainer = dspy.ChainOfThought(MedicationExplanation)
_interaction_explainer = dspy.ChainOfThought(InteractionExplanation)
_adherence_checker = dspy.ChainOfThought(AdherenceCheckIn)
_conversation_responder = dspy.ChainOfThought(ConversationResponse)


# ---------------------------------------------------------------------------
# Public API (async)
# ---------------------------------------------------------------------------


async def explain_medication(
    medication_name: str,
    dosage_info: str,
    patient_medications: list[str],
) -> dspy.Prediction:
    """Explain a medication in plain 繁體中文.

    Uses the creative (Pro) LM for accuracy on medical content.
    """
    configure_dspy()
    with dspy.context(lm=get_dspy_creative_lm()):
        return await _medication_explainer.acall(
            medication_name=medication_name,
            dosage_info=dosage_info,
            patient_medications=patient_medications,
        )


async def explain_interaction(
    drug_a: str,
    drug_b: str,
    interaction_data: str,
) -> dspy.Prediction:
    """Explain a drug interaction using authoritative RxNorm data.

    Uses the fast (Flash) LM — interaction data is already authoritative,
    we just need to translate it to plain language.
    """
    configure_dspy()
    return await _interaction_explainer.acall(
        drug_a=drug_a,
        drug_b=drug_b,
        interaction_data=interaction_data,
    )


async def check_adherence(
    user_response: str,
    scheduled_medications: list[str],
) -> dspy.Prediction:
    """Parse a user's adherence check-in response.

    Uses the fast (Flash) LM for real-time pipeline speed.
    """
    configure_dspy()
    return await _adherence_checker.acall(
        user_response=user_response,
        scheduled_medications=scheduled_medications,
    )


async def respond_to_message(
    user_message: str,
    medication_context: list[str],
    conversation_summary: str = "none",
) -> dspy.Prediction:
    """Respond to a general user message with intent detection.

    Uses the fast (Flash) LM for webhook latency.
    """
    configure_dspy()
    return await _conversation_responder.acall(
        user_message=user_message,
        medication_context=medication_context,
        conversation_summary=conversation_summary,
    )
