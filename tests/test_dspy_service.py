"""Tests for DSPy service — medication intelligence layer."""

from unittest.mock import AsyncMock, MagicMock, patch

import dspy
import pytest

from app.services.dspy_service import (
    AdherenceCheckIn,
    ConversationResponse,
    InteractionExplanation,
    MedicationExplanation,
    check_adherence,
    configure_dspy,
    explain_interaction,
    explain_medication,
    respond_to_message,
)


class TestConfigureDspy:
    """Test DSPy configuration."""

    def test_configure_is_idempotent(self) -> None:
        """Calling configure_dspy() multiple times is safe."""
        import app.services.dspy_service as module

        module._configured = False
        with patch.object(dspy, "configure") as mock_configure:
            configure_dspy()
            configure_dspy()
            # Should only configure once
            mock_configure.assert_called_once()
        module._configured = False  # Reset for other tests


class TestSignatureDefinitions:
    """Test that DSPy signatures have correct field definitions."""

    def test_medication_explanation_fields(self) -> None:
        """MedicationExplanation has the expected input/output fields."""
        input_fields = MedicationExplanation.input_fields
        output_fields = MedicationExplanation.output_fields
        assert "medication_name" in input_fields
        assert "dosage_info" in input_fields
        assert "patient_medications" in input_fields
        assert "explanation" in output_fields
        assert "warnings" in output_fields
        assert "take_with_food" in output_fields

    def test_interaction_explanation_fields(self) -> None:
        """InteractionExplanation has the expected input/output fields."""
        input_fields = InteractionExplanation.input_fields
        output_fields = InteractionExplanation.output_fields
        assert "drug_a" in input_fields
        assert "drug_b" in input_fields
        assert "interaction_data" in input_fields
        assert "explanation" in output_fields
        assert "severity" in output_fields
        assert "action_needed" in output_fields

    def test_adherence_checkin_fields(self) -> None:
        """AdherenceCheckIn has the expected input/output fields."""
        input_fields = AdherenceCheckIn.input_fields
        output_fields = AdherenceCheckIn.output_fields
        assert "user_response" in input_fields
        assert "scheduled_medications" in input_fields
        assert "taken" in output_fields
        assert "missed" in output_fields
        assert "follow_up" in output_fields

    def test_conversation_response_fields(self) -> None:
        """ConversationResponse has the expected input/output fields."""
        input_fields = ConversationResponse.input_fields
        output_fields = ConversationResponse.output_fields
        assert "user_message" in input_fields
        assert "medication_context" in input_fields
        assert "conversation_summary" in input_fields
        assert "response" in output_fields
        assert "intent" in output_fields
        assert "mentioned_drug" in output_fields


class TestExplainMedication:
    """Test the explain_medication async function."""

    @pytest.mark.asyncio
    async def test_calls_chain_of_thought_with_creative_lm(self) -> None:
        """explain_medication uses the creative (Pro) LM."""
        mock_prediction = dspy.Prediction(
            explanation="這是一種降血糖的藥物。飯後服用，一天兩次。",
            warnings=["不要空腹吃", "可能會胃不舒服"],
            take_with_food=True,
        )

        with (
            patch("app.services.dspy_service._medication_explainer") as mock_explainer,
            patch("app.services.dspy_service.configure_dspy"),
            patch("app.services.dspy_service.get_dspy_creative_lm") as mock_lm,
        ):
            mock_explainer.acall = AsyncMock(return_value=mock_prediction)
            mock_lm.return_value = MagicMock()

            result = await explain_medication(
                medication_name="Metformin",
                dosage_info="500mg twice daily",
                patient_medications=["Lisinopril", "Aspirin"],
            )

            assert result.explanation == "這是一種降血糖的藥物。飯後服用，一天兩次。"
            assert len(result.warnings) == 2
            assert result.take_with_food is True
            mock_explainer.acall.assert_called_once()


class TestExplainInteraction:
    """Test the explain_interaction async function."""

    @pytest.mark.asyncio
    async def test_returns_interaction_explanation(self) -> None:
        """explain_interaction returns severity and plain-language explanation."""
        mock_prediction = dspy.Prediction(
            explanation="這兩種藥物一起使用可能會增加出血風險。",
            severity="moderate",
            action_needed="請在下次看醫生時告訴他您同時在服用這兩種藥。",
        )

        with (
            patch("app.services.dspy_service._interaction_explainer") as mock_explainer,
            patch("app.services.dspy_service.configure_dspy"),
        ):
            mock_explainer.acall = AsyncMock(return_value=mock_prediction)

            result = await explain_interaction(
                drug_a="Warfarin",
                drug_b="Aspirin",
                interaction_data=(
                    '{"severity": "moderate", "description": "increased bleeding risk"}'
                ),
            )

            assert result.severity == "moderate"
            assert "出血" in result.explanation
            mock_explainer.acall.assert_called_once()


class TestCheckAdherence:
    """Test the check_adherence async function."""

    @pytest.mark.asyncio
    async def test_parses_adherence_response(self) -> None:
        """check_adherence correctly parses taken/missed medications."""
        mock_prediction = dspy.Prediction(
            taken=["Metformin", "Lisinopril"],
            missed=["Aspirin"],
            follow_up="很好！大部分的藥都吃了。阿斯匹靈記得等一下吃喔！",
        )

        with (
            patch("app.services.dspy_service._adherence_checker") as mock_checker,
            patch("app.services.dspy_service.configure_dspy"),
        ):
            mock_checker.acall = AsyncMock(return_value=mock_prediction)

            result = await check_adherence(
                user_response="早上的降血糖藥和血壓藥都吃了，阿斯匹靈還沒",
                scheduled_medications=["Metformin", "Lisinopril", "Aspirin"],
            )

            assert "Metformin" in result.taken
            assert "Aspirin" in result.missed
            assert result.follow_up  # Non-empty


class TestRespondToMessage:
    """Test the respond_to_message async function."""

    @pytest.mark.asyncio
    async def test_detects_medication_query_intent(self) -> None:
        """respond_to_message detects medication-related intent."""
        mock_prediction = dspy.Prediction(
            response="Metformin 是一種幫助控制血糖的藥物。請詢問您的醫生。",
            intent="medication_query",
            mentioned_drug="Metformin",
        )

        with (
            patch("app.services.dspy_service._conversation_responder") as mock_responder,
            patch("app.services.dspy_service.configure_dspy"),
        ):
            mock_responder.acall = AsyncMock(return_value=mock_prediction)

            result = await respond_to_message(
                user_message="Metformin 是什麼藥？",
                medication_context=["Lisinopril"],
            )

            assert result.intent == "medication_query"
            assert result.mentioned_drug == "Metformin"

    @pytest.mark.asyncio
    async def test_handles_greeting(self) -> None:
        """respond_to_message handles greetings gracefully."""
        mock_prediction = dspy.Prediction(
            response="您好！我是 MedBuddy，您的用藥小幫手。有什麼我可以幫您的嗎？",
            intent="greeting",
            mentioned_drug="none",
        )

        with (
            patch("app.services.dspy_service._conversation_responder") as mock_responder,
            patch("app.services.dspy_service.configure_dspy"),
        ):
            mock_responder.acall = AsyncMock(return_value=mock_prediction)

            result = await respond_to_message(
                user_message="你好",
                medication_context=[],
            )

            assert result.intent == "greeting"
            assert result.mentioned_drug == "none"
