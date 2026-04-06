"""LangGraph StateGraph pipeline for MedBuddy.

Multi-stage pipeline: route → STT (if audio) → comprehension → drug lookup → TTS → reply.
Each LINE user gets their own thread for conversational memory via AsyncPostgresSaver.
"""

import logging
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.services import drug_service, dspy_service, sanitiser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class MedBuddyState(TypedDict):
    """State passed between pipeline nodes."""

    messages: Annotated[list[BaseMessage], add_messages]
    line_user_id: str
    audio_bytes: bytes | None
    transcript: str | None
    medication_context: list[str]
    explanation_text: str | None
    tts_audio_bytes: bytes | None
    stage: str
    intent: str | None
    mentioned_drug: str | None
    sanitisation_warnings: list[str]


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


async def route_input_node(state: MedBuddyState) -> dict:
    """Determine whether the input is audio or text and set the stage."""
    if state.get("audio_bytes"):
        return {"stage": "stt"}
    # Text input — extract the latest user message
    messages = state.get("messages", [])
    transcript = None
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            transcript = msg.content
            break
    return {"stage": "comprehension", "transcript": transcript}


async def stt_node(state: MedBuddyState) -> dict:
    """Transcribe audio to text using Google Cloud STT v2 (Chirp 3).

    This node is a placeholder — actual STT integration is in voice_service.py.
    The voice_service transcribes and sets the transcript before the pipeline runs.
    """
    # Audio is transcribed before pipeline entry (in the webhook handler)
    # This node exists for graph completeness and future streaming support
    transcript = state.get("transcript", "")
    if not transcript:
        return {
            "stage": "reply",
            "explanation_text": "抱歉，我沒有聽清楚。請再說一次，或者用打字的方式告訴我。",
        }
    return {"stage": "comprehension"}


async def comprehension_node(state: MedBuddyState) -> dict:
    """Process the user's message with DSPy + Gemini.

    Detects intent, extracts drug mentions, and generates a response.
    """
    transcript = state.get("transcript", "")
    if not transcript:
        return {
            "stage": "reply",
            "explanation_text": "抱歉，我沒有收到您的訊息。請再試一次。",
        }

    # Sanitise input before LLM call
    sanitised_text, warnings = sanitiser.sanitise_input(transcript)
    if not sanitised_text:
        return {
            "stage": "reply",
            "explanation_text": "抱歉，我無法處理這個訊息。請用其他方式告訴我您的問題。",
            "sanitisation_warnings": warnings,
        }

    medication_context = state.get("medication_context", [])

    # Use DSPy ConversationResponse for intent detection + response
    result = await dspy_service.respond_to_message(
        user_message=sanitised_text,
        medication_context=medication_context,
    )

    # Scan output before sending to user
    safe_response = sanitiser.scan_output(result.response)

    return {
        "messages": [AIMessage(content=safe_response)],
        "stage": "comprehension_done",
        "explanation_text": safe_response,
        "intent": result.intent,
        "mentioned_drug": result.mentioned_drug,
        "sanitisation_warnings": warnings,
    }


async def drug_lookup_node(state: MedBuddyState) -> dict:
    """Look up drug interactions via RxNorm API.

    Only runs when the user mentions a drug and has other medications.
    """
    mentioned_drug = state.get("mentioned_drug", "none")
    medication_context = state.get("medication_context", [])

    if mentioned_drug == "none" or not medication_context:
        return {"stage": "tts"}

    # Check interactions between mentioned drug and each existing medication
    interactions_found = []
    for existing_drug in medication_context:
        if existing_drug.lower() == mentioned_drug.lower():
            continue
        interaction_data = await drug_service.check_drug_interaction(mentioned_drug, existing_drug)
        if '"interactions": []' not in interaction_data:
            interactions_found.append(
                {
                    "drug_a": mentioned_drug,
                    "drug_b": existing_drug,
                    "data": interaction_data,
                }
            )

    if not interactions_found:
        return {"stage": "tts"}

    # Explain the first interaction found using DSPy
    first = interactions_found[0]
    explanation = await dspy_service.explain_interaction(
        drug_a=first["drug_a"],
        drug_b=first["drug_b"],
        interaction_data=first["data"],
    )

    safe_explanation = sanitiser.scan_output(explanation.explanation)
    safe_action = sanitiser.scan_output(explanation.action_needed)

    # Append interaction warning to the existing explanation
    severity_emoji = {"none": "✅", "mild": "⚠️", "moderate": "⚠️", "severe": "🔴"}.get(
        explanation.severity, "⚠️"
    )
    interaction_text = f"\n\n{severity_emoji} 藥物交互作用提醒：\n{safe_explanation}\n{safe_action}"

    current_explanation = state.get("explanation_text", "")
    return {
        "stage": "tts",
        "explanation_text": current_explanation + interaction_text,
    }


async def tts_node(state: MedBuddyState) -> dict:
    """Generate TTS audio from the explanation text.

    Placeholder — actual TTS is handled by voice_service.py after pipeline completion.
    """
    # TTS is generated after pipeline completes (in the webhook handler)
    # to keep the pipeline fast and allow text reply to go out immediately
    return {"stage": "reply"}


async def reply_node(state: MedBuddyState) -> dict:
    """Final node — marks pipeline as complete.

    The actual LINE reply is sent by the webhook handler after pipeline completion.
    """
    return {"stage": "done"}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def route_after_input(state: MedBuddyState) -> Literal["stt_node", "comprehension_node"]:
    """Route to STT if audio, otherwise straight to comprehension."""
    if state.get("stage") == "stt":
        return "stt_node"
    return "comprehension_node"


def route_after_comprehension(
    state: MedBuddyState,
) -> Literal["drug_lookup_node", "tts_node", "reply_node"]:
    """Route to drug lookup if a drug is mentioned, otherwise to TTS."""
    stage = state.get("stage", "")
    if stage == "reply":
        # Error or empty input — skip to reply
        return "reply_node"

    intent = state.get("intent", "")
    mentioned_drug = state.get("mentioned_drug", "none")
    medication_context = state.get("medication_context", [])

    # Check drug interactions if a drug is mentioned and user has other meds
    if (
        intent in ("medication_query", "interaction_query")
        and mentioned_drug != "none"
        and medication_context
    ):
        return "drug_lookup_node"

    return "tts_node"


# ---------------------------------------------------------------------------
# Graph Builder
# ---------------------------------------------------------------------------


def build_pipeline() -> StateGraph:
    """Build the MedBuddy LangGraph pipeline.

    Returns a compiled StateGraph. Call with checkpointer for persistence.
    """
    builder = StateGraph(MedBuddyState)

    # Add nodes
    builder.add_node("route_input", route_input_node)
    builder.add_node("stt_node", stt_node)
    builder.add_node("comprehension_node", comprehension_node)
    builder.add_node("drug_lookup_node", drug_lookup_node)
    builder.add_node("tts_node", tts_node)
    builder.add_node("reply_node", reply_node)

    # Wire edges
    builder.add_edge(START, "route_input")
    builder.add_conditional_edges("route_input", route_after_input)
    builder.add_edge("stt_node", "comprehension_node")
    builder.add_conditional_edges("comprehension_node", route_after_comprehension)
    builder.add_edge("drug_lookup_node", "tts_node")
    builder.add_edge("tts_node", "reply_node")
    builder.add_edge("reply_node", END)

    return builder


def compile_pipeline(checkpointer=None):
    """Compile the pipeline with optional checkpointer.

    Args:
        checkpointer: LangGraph checkpointer (e.g., AsyncPostgresSaver).
            If None, pipeline runs without persistence.

    Returns:
        Compiled graph ready for ainvoke().
    """
    builder = build_pipeline()
    return builder.compile(checkpointer=checkpointer)
