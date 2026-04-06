"""Message handler — routes LINE message events to the appropriate service.

Centralises the webhook event processing logic that was previously inline
in main.py. Handles text, audio, and special commands (data deletion).
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.handlers.onboarding_handler import (
    ensure_user_exists,
    handle_data_deletion,
    is_delete_command,
)
from app.services import line_service, rate_limiter, voice_service
from app.services.pipeline import MedBuddyState  # noqa: TC001
from app.services.sanitiser import scan_output

logger = logging.getLogger(__name__)


async def handle_message_event(
    event: dict,
    pipeline,
    session: AsyncSession,
) -> None:
    """Handle a LINE message event end-to-end.

    Args:
        event: LINE webhook message event.
        pipeline: Compiled LangGraph pipeline.
        session: Async database session.
    """
    reply_token = event.get("replyToken", "")
    user_id = event.get("source", {}).get("userId", "")
    message = event.get("message", {})
    message_type = message.get("type", "")
    message_id = message.get("id", "")

    if not user_id:
        logger.warning("Message event without user ID")
        return

    # Rate limiting check
    if rate_limiter.is_rate_limited(user_id):
        await line_service.reply_text(
            reply_token,
            "您的問題太多了，請稍等一下再試。",
        )
        return

    # Check for data deletion command
    if message_type == "text" and is_delete_command(message.get("text", "")):
        await handle_data_deletion(user_id, session)
        return

    # Ensure user exists in DB (creates on first interaction, records consent)
    user = await ensure_user_exists(user_id, session)

    # Send immediate "thinking" reply
    try:
        await line_service.reply_text(reply_token, "正在為您查詢...")
    except Exception:
        logger.warning("Failed to send immediate reply to user %s", user_id)

    # Prepare pipeline input
    transcript = None
    audio_bytes = None

    if message_type == "text":
        transcript = message.get("text", "")
    elif message_type == "audio":
        try:
            raw_audio = await line_service.download_content(message_id)
            transcript = await voice_service.transcribe_audio(raw_audio)
            audio_bytes = raw_audio

            if transcript:
                await line_service.push_text(user_id, f"您是不是說：「{transcript}」")
        except Exception:
            logger.exception("Voice transcription failed for user %s", user_id)
            await line_service.push_text(
                user_id,
                "抱歉，我沒有聽清楚。請再說一次，或者用打字的方式告訴我。",
            )
            return
    else:
        await line_service.push_text(user_id, "目前我只能處理文字和語音訊息喔！")
        return

    if not transcript:
        return

    # Load user's medication context from DB
    medication_names = []
    if user.medications:
        from app.services.encryption import decrypt

        medication_names = [
            decrypt(med.drug_name_en_encrypted) for med in user.medications if med.is_active
        ]

    # Run LangGraph pipeline
    try:
        from langchain_core.messages import HumanMessage

        initial_state: MedBuddyState = {
            "messages": [HumanMessage(content=transcript)],
            "line_user_id": user_id,
            "audio_bytes": audio_bytes,
            "transcript": transcript,
            "medication_context": medication_names,
            "explanation_text": None,
            "tts_audio_bytes": None,
            "stage": "",
            "intent": None,
            "mentioned_drug": None,
            "sanitisation_warnings": [],
        }

        config = {"configurable": {"thread_id": user_id}}
        result = await pipeline.ainvoke(initial_state, config)

        explanation = result.get("explanation_text", "")
        if explanation:
            safe_text = scan_output(explanation)
            await line_service.push_text(user_id, safe_text)

            # TTS audio generation (best-effort)
            try:
                tts_audio = await voice_service.synthesise_speech(safe_text)
                if tts_audio:
                    logger.info(
                        "TTS audio generated for user %s (%d bytes)",
                        user_id,
                        len(tts_audio),
                    )
            except Exception:
                logger.warning("TTS generation failed for user %s", user_id)
        else:
            await line_service.push_text(
                user_id,
                "抱歉，目前無法處理您的問題。請稍後再試，或直接詢問您的醫生。",
            )

    except Exception:
        logger.exception("Pipeline failed for user %s", user_id)
        await line_service.push_text(
            user_id,
            "抱歉，系統暫時出了問題。請稍後再試，或直接詢問您的醫生。",
        )
