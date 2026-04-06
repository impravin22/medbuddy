"""Tests for LangGraph pipeline — MedBuddy processing pipeline."""

from unittest.mock import AsyncMock, patch

import dspy
import pytest
from langchain_core.messages import HumanMessage

from app.services.pipeline import (
    MedBuddyState,
    build_pipeline,
    compile_pipeline,
    comprehension_node,
    drug_lookup_node,
    route_after_comprehension,
    route_after_input,
    route_input_node,
    stt_node,
)


class TestRouteInputNode:
    """Test the route_input node."""

    @pytest.mark.asyncio
    async def test_routes_audio_to_stt(self) -> None:
        """Audio input routes to STT stage."""
        state: MedBuddyState = {
            "messages": [],
            "line_user_id": "U1234",
            "audio_bytes": b"fake-audio",
            "transcript": None,
            "medication_context": [],
            "explanation_text": None,
            "tts_audio_bytes": None,
            "stage": "",
            "intent": None,
            "mentioned_drug": None,
            "sanitisation_warnings": [],
        }
        result = await route_input_node(state)
        assert result["stage"] == "stt"

    @pytest.mark.asyncio
    async def test_routes_text_to_comprehension(self) -> None:
        """Text input routes to comprehension stage."""
        state: MedBuddyState = {
            "messages": [HumanMessage(content="Metformin 是什麼？")],
            "line_user_id": "U1234",
            "audio_bytes": None,
            "transcript": None,
            "medication_context": [],
            "explanation_text": None,
            "tts_audio_bytes": None,
            "stage": "",
            "intent": None,
            "mentioned_drug": None,
            "sanitisation_warnings": [],
        }
        result = await route_input_node(state)
        assert result["stage"] == "comprehension"
        assert result["transcript"] == "Metformin 是什麼？"


class TestSttNode:
    """Test the STT node."""

    @pytest.mark.asyncio
    async def test_empty_transcript_returns_error(self) -> None:
        """Empty transcript returns a helpful error message."""
        state: MedBuddyState = {
            "messages": [],
            "line_user_id": "U1234",
            "audio_bytes": b"audio",
            "transcript": "",
            "medication_context": [],
            "explanation_text": None,
            "tts_audio_bytes": None,
            "stage": "stt",
            "intent": None,
            "mentioned_drug": None,
            "sanitisation_warnings": [],
        }
        result = await stt_node(state)
        assert result["stage"] == "reply"
        assert "沒有聽清楚" in result["explanation_text"]

    @pytest.mark.asyncio
    async def test_valid_transcript_continues(self) -> None:
        """Valid transcript continues to comprehension."""
        state: MedBuddyState = {
            "messages": [],
            "line_user_id": "U1234",
            "audio_bytes": b"audio",
            "transcript": "我要問藥的問題",
            "medication_context": [],
            "explanation_text": None,
            "tts_audio_bytes": None,
            "stage": "stt",
            "intent": None,
            "mentioned_drug": None,
            "sanitisation_warnings": [],
        }
        result = await stt_node(state)
        assert result["stage"] == "comprehension"


class TestComprehensionNode:
    """Test the comprehension node."""

    @pytest.mark.asyncio
    async def test_processes_medication_query(self) -> None:
        """Comprehension node calls DSPy and returns explanation."""
        state: MedBuddyState = {
            "messages": [],
            "line_user_id": "U1234",
            "audio_bytes": None,
            "transcript": "Metformin 是什麼藥",
            "medication_context": ["Lisinopril"],
            "explanation_text": None,
            "tts_audio_bytes": None,
            "stage": "comprehension",
            "intent": None,
            "mentioned_drug": None,
            "sanitisation_warnings": [],
        }

        mock_prediction = dspy.Prediction(
            response="Metformin 是一種降血糖藥。請詢問您的醫生。",
            intent="medication_query",
            mentioned_drug="Metformin",
        )

        with patch(
            "app.services.pipeline.dspy_service.respond_to_message",
            new_callable=AsyncMock,
            return_value=mock_prediction,
        ):
            result = await comprehension_node(state)

        assert result["intent"] == "medication_query"
        assert result["mentioned_drug"] == "Metformin"
        assert "Metformin" in result["explanation_text"]

    @pytest.mark.asyncio
    async def test_empty_transcript_returns_error(self) -> None:
        """Empty transcript returns an error message."""
        state: MedBuddyState = {
            "messages": [],
            "line_user_id": "U1234",
            "audio_bytes": None,
            "transcript": "",
            "medication_context": [],
            "explanation_text": None,
            "tts_audio_bytes": None,
            "stage": "comprehension",
            "intent": None,
            "mentioned_drug": None,
            "sanitisation_warnings": [],
        }
        result = await comprehension_node(state)
        assert result["stage"] == "reply"
        assert "再試一次" in result["explanation_text"]


class TestDrugLookupNode:
    """Test the drug lookup node."""

    @pytest.mark.asyncio
    async def test_no_drug_mentioned_skips(self) -> None:
        """No mentioned drug skips to TTS."""
        state: MedBuddyState = {
            "messages": [],
            "line_user_id": "U1234",
            "audio_bytes": None,
            "transcript": "你好",
            "medication_context": ["Lisinopril"],
            "explanation_text": "Hello",
            "tts_audio_bytes": None,
            "stage": "comprehension_done",
            "intent": "greeting",
            "mentioned_drug": "none",
            "sanitisation_warnings": [],
        }
        result = await drug_lookup_node(state)
        assert result["stage"] == "tts"

    @pytest.mark.asyncio
    async def test_drug_with_no_interactions(self) -> None:
        """Drug mentioned but no interactions found skips to TTS."""
        state: MedBuddyState = {
            "messages": [],
            "line_user_id": "U1234",
            "audio_bytes": None,
            "transcript": "Aspirin 是什麼",
            "medication_context": ["Metformin"],
            "explanation_text": "Aspirin 是一種止痛藥。",
            "tts_audio_bytes": None,
            "stage": "comprehension_done",
            "intent": "medication_query",
            "mentioned_drug": "Aspirin",
            "sanitisation_warnings": [],
        }

        with patch(
            "app.services.pipeline.drug_service.check_drug_interaction",
            new_callable=AsyncMock,
            return_value='{"interactions": []}',
        ):
            result = await drug_lookup_node(state)

        assert result["stage"] == "tts"

    @pytest.mark.asyncio
    async def test_drug_with_interaction_appends_warning(self) -> None:
        """Drug interaction found appends warning to explanation."""
        state: MedBuddyState = {
            "messages": [],
            "line_user_id": "U1234",
            "audio_bytes": None,
            "transcript": "Warfarin 是什麼",
            "medication_context": ["Aspirin"],
            "explanation_text": "Warfarin 是一種抗凝血藥。",
            "tts_audio_bytes": None,
            "stage": "comprehension_done",
            "intent": "medication_query",
            "mentioned_drug": "Warfarin",
            "sanitisation_warnings": [],
        }

        interaction_data = '{"fullInteractionTypeGroup": [{"severity": "high"}]}'

        mock_explanation = dspy.Prediction(
            explanation="這兩種藥物可能增加出血風險。",
            severity="severe",
            action_needed="請在下次看醫生時告訴他。",
        )

        with (
            patch(
                "app.services.pipeline.drug_service.check_drug_interaction",
                new_callable=AsyncMock,
                return_value=interaction_data,
            ),
            patch(
                "app.services.pipeline.dspy_service.explain_interaction",
                new_callable=AsyncMock,
                return_value=mock_explanation,
            ),
        ):
            result = await drug_lookup_node(state)

        assert result["stage"] == "tts"
        assert "出血" in result["explanation_text"]
        assert "🔴" in result["explanation_text"]  # severe emoji


class TestRouting:
    """Test conditional routing functions."""

    def test_route_after_input_audio(self) -> None:
        """Audio stage routes to STT."""
        state = {"stage": "stt"}
        assert route_after_input(state) == "stt_node"

    def test_route_after_input_text(self) -> None:
        """Non-audio stage routes to comprehension."""
        state = {"stage": "comprehension"}
        assert route_after_input(state) == "comprehension_node"

    def test_route_after_comprehension_to_drug_lookup(self) -> None:
        """Drug query with existing meds routes to drug lookup."""
        state = {
            "stage": "comprehension_done",
            "intent": "medication_query",
            "mentioned_drug": "Warfarin",
            "medication_context": ["Aspirin"],
        }
        assert route_after_comprehension(state) == "drug_lookup_node"

    def test_route_after_comprehension_to_tts(self) -> None:
        """Greeting intent routes to TTS (no drug lookup)."""
        state = {
            "stage": "comprehension_done",
            "intent": "greeting",
            "mentioned_drug": "none",
            "medication_context": [],
        }
        assert route_after_comprehension(state) == "tts_node"

    def test_route_after_comprehension_error_to_reply(self) -> None:
        """Error stage routes directly to reply."""
        state = {"stage": "reply"}
        assert route_after_comprehension(state) == "reply_node"


class TestGraphConstruction:
    """Test graph building and compilation."""

    def test_build_pipeline_returns_stategraph(self) -> None:
        """build_pipeline returns a valid StateGraph builder."""
        builder = build_pipeline()
        assert builder is not None

    def test_compile_pipeline_without_checkpointer(self) -> None:
        """Pipeline compiles without a checkpointer (for testing)."""
        graph = compile_pipeline(checkpointer=None)
        assert graph is not None

    def test_graph_has_expected_nodes(self) -> None:
        """Compiled graph has all expected nodes."""
        graph = compile_pipeline(checkpointer=None)
        node_names = set(graph.nodes.keys())
        expected_nodes = {
            "route_input",
            "stt_node",
            "comprehension_node",
            "drug_lookup_node",
            "tts_node",
            "reply_node",
        }
        assert expected_nodes.issubset(node_names)
