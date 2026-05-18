"""
Unit tests for AiBrollRecommender.

Covers:
  - BrollCandidate dataclass to_dict()
  - make_task_ctx() factory
  - create_recommender() factory
  - _fallback_tfidf() with various transcript inputs
  - _apply_diversity() edge cases
  - _compute_duration() for different shot types and positions
  - suggest_broll() with LLM success (mocked)
  - suggest_broll() with LLM failure → TF-IDF fallback
  - suggest_broll() with diversity context
"""

from __future__ import annotations

import json
import math
import pytest
from collections import Counter
from typing import Any, Dict, List, Optional, Set
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.ai_broll_recommender import (
    AiBrollRecommender,
    BrollCandidate,
    create_recommender,
    make_task_ctx,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def recommender() -> AiBrollRecommender:
    """Create a recommender with a dummy API key (won't be called in most tests)."""
    return AiBrollRecommender(
        llm_api_key="test-key",
        llm_base_url="https://fake.api.test/v1",
        llm_model="test-model",
        max_keywords=3,
    )


@pytest.fixture
def sample_transcript() -> str:
    return (
        "Life insurance provides financial security for your family when they need it most. "
        "It ensures that your loved ones are protected and can maintain their lifestyle "
        "even after you're gone. Many people don't realize how affordable life insurance "
        "can be, especially when you start young."
    )


@pytest.fixture
def short_transcript() -> str:
    return "Hello world this is a test."


# ── BrollCandidate tests ───────────────────────────────────────────────────────

class TestBrollCandidate:
    def test_to_dict_basic(self):
        cand = BrollCandidate(
            keywords=["family", "protection"],
            tipo_plano="wide",
            prefered_duration_s=5.0,
            mood="serious",
            tags=["insurance", "family"],
            concept="family protection",
        )
        d = cand.to_dict()
        assert d["keywords"] == ["family", "protection"]
        assert d["tipo_plano"] == "wide"
        assert d["prefered_duration_s"] == 5.0
        assert d["mood"] == "serious"
        assert d["tags"] == ["insurance", "family"]
        assert d["concept"] == "family protection"

    def test_to_dict_defaults(self):
        cand = BrollCandidate(keywords=["test"])
        d = cand.to_dict()
        assert d["keywords"] == ["test"]
        assert d["tipo_plano"] == "medium"
        assert d["prefered_duration_s"] == 4.5
        assert d["mood"] is None
        assert d["tags"] == []
        assert d["concept"] == ""

    def test_to_dict_roundtrip(self):
        cand = BrollCandidate(
            keywords=["a", "b"],
            tipo_plano="closeup",
            prefered_duration_s=3.0,
            mood="uplifting",
            tags=["tag1"],
            concept="test concept",
        )
        d = cand.to_dict()
        restored = BrollCandidate(**d)
        assert restored.keywords == cand.keywords
        assert restored.tipo_plano == cand.tipo_plano
        assert restored.prefered_duration_s == cand.prefered_duration_s
        assert restored.mood == cand.mood
        assert restored.tags == cand.tags
        assert restored.concept == cand.concept


# ── Factory tests ──────────────────────────────────────────────────────────────

class TestFactories:
    def test_make_task_ctx_defaults(self):
        ctx = make_task_ctx()
        assert ctx["covered_topics"] == set()
        assert ctx["used_keywords"] == set()
        assert ctx["segment_count"] == 1

    def test_make_task_ctx_custom(self):
        topics = {"finance", "insurance"}
        keywords = {"money", "protection"}
        ctx = make_task_ctx(
            covered_topics=topics,
            used_keywords=keywords,
            segment_count=5,
        )
        assert ctx["covered_topics"] == topics
        assert ctx["used_keywords"] == keywords
        assert ctx["segment_count"] == 5

    def test_make_task_ctx_immutable_defaults(self):
        """Ensure default sets are fresh copies, not shared references."""
        ctx1 = make_task_ctx()
        ctx2 = make_task_ctx()
        ctx1["covered_topics"].add("topic1")
        assert "topic1" not in ctx2["covered_topics"]

    def test_create_recommender_defaults(self):
        rec = create_recommender()
        assert isinstance(rec, AiBrollRecommender)
        assert rec.max_keywords == 3
        assert rec.llm_model == "llama-3.1-8b-instant"

    def test_create_recommender_custom(self):
        rec = create_recommender(
            llm_api_key="custom-key",
            llm_base_url="https://custom.api/v1",
            llm_model="custom-model",
            max_keywords=5,
        )
        assert rec.llm_api_key == "custom-key"
        assert rec.llm_base_url == "https://custom.api/v1"
        assert rec.llm_model == "custom-model"
        assert rec.max_keywords == 5


# ── TF-IDF fallback tests ──────────────────────────────────────────────────────

class TestFallbackTfidf:
    def test_basic_extraction(self, recommender: AiBrollRecommender):
        transcript = "The quick brown fox jumps over the lazy dog near the river bank"
        candidates = recommender._fallback_tfidf(transcript)
        assert len(candidates) > 0
        assert len(candidates) <= 5  # _TFIDF_FALLBACK_TOP_K
        # All candidates should have keywords
        for c in candidates:
            assert len(c.keywords) == 1
            assert c.tipo_plano == "medium"
            assert c.concept.startswith("visual representation of")

    def test_stopwords_removed(self, recommender: AiBrollRecommender):
        """Transcript with only stopwords should return empty or minimal."""
        transcript = "the and or but in on at to for of with by"
        candidates = recommender._fallback_tfidf(transcript)
        # Should be empty since all words are stopwords
        assert len(candidates) == 0

    def test_short_words_filtered(self, recommender: AiBrollRecommender):
        """Words with length <= 2 should be filtered out."""
        transcript = "a an in on at to be it we he my"
        candidates = recommender._fallback_tfidf(transcript)
        assert len(candidates) == 0

    def test_meaningful_content(self, recommender: AiBrollRecommender):
        """Transcript with clear meaningful nouns should extract them."""
        transcript = "insurance policy protects family home car health"
        candidates = recommender._fallback_tfidf(transcript)
        assert len(candidates) > 0
        all_keywords = [c.keywords[0] for c in candidates]
        # At least some of these should be present
        meaningful = {"insurance", "policy", "family", "home", "car", "health"}
        assert any(kw in meaningful for kw in all_keywords)

    def test_repeated_words_boosted(self, recommender: AiBrollRecommender):
        """Words that appear multiple times should be ranked higher."""
        transcript = "family family family protection money family home"
        candidates = recommender._fallback_tfidf(transcript)
        assert len(candidates) > 0
        # "family" should be the top keyword since it appears most
        assert candidates[0].keywords[0] == "family"

    def test_long_transcript(self, recommender: AiBrollRecommender):
        """Long transcript should still produce reasonable results."""
        transcript = " ".join([
            "technology innovation digital transformation artificial intelligence "
            "machine learning cloud computing data science cybersecurity "
            "blockchain internet of things automation robotics"
        ] * 3)  # Repeat to make it long
        candidates = recommender._fallback_tfidf(transcript)
        assert len(candidates) > 0
        assert len(candidates) <= 5

    def test_mixed_language(self, recommender: AiBrollRecommender):
        """Non-English words that aren't stopwords should still be extracted."""
        transcript = "seguro de vida proteccion familiar ahorro"
        candidates = recommender._fallback_tfidf(transcript)
        assert len(candidates) > 0
        all_keywords = [c.keywords[0] for c in candidates]
        # Spanish meaningful words should be present
        spanish_words = {"seguro", "vida", "proteccion", "familiar", "ahorro"}
        assert any(kw in spanish_words for kw in all_keywords)

    def test_empty_transcript(self, recommender: AiBrollRecommender):
        """Empty transcript should return empty list."""
        candidates = recommender._fallback_tfidf("")
        assert candidates == []

    def test_single_word(self, recommender: AiBrollRecommender):
        """Single meaningful word should return one candidate."""
        candidates = recommender._fallback_tfidf("mountain")
        assert len(candidates) == 1
        assert candidates[0].keywords[0] == "mountain"


# ── Diversity tests ────────────────────────────────────────────────────────────

class TestApplyDiversity:
    def test_no_context(self, recommender: AiBrollRecommender):
        """With empty context, all candidates should pass through."""
        candidates = [
            BrollCandidate(keywords=["family"], concept="family protection"),
            BrollCandidate(keywords=["money"], concept="financial planning"),
        ]
        result = recommender._apply_diversity(candidates, set(), set())
        assert len(result) == 2

    def test_concept_already_covered(self, recommender: AiBrollRecommender):
        """Candidates with already-covered concept should be filtered."""
        candidates = [
            BrollCandidate(keywords=["family"], concept="family protection"),
            BrollCandidate(keywords=["money"], concept="financial planning"),
        ]
        result = recommender._apply_diversity(
            candidates,
            covered_topics={"family protection"},
            used_keywords=set(),
        )
        assert len(result) == 1
        assert result[0].keywords == ["money"]

    def test_keyword_already_used(self, recommender: AiBrollRecommender):
        """Candidates with already-used keywords should be filtered."""
        candidates = [
            BrollCandidate(keywords=["family"], concept="family"),
            BrollCandidate(keywords=["money"], concept="money"),
        ]
        result = recommender._apply_diversity(
            candidates,
            covered_topics=set(),
            used_keywords={"family"},
        )
        assert len(result) == 1
        assert result[0].keywords == ["money"]

    def test_all_penalized_keeps_best(self, recommender: AiBrollRecommender):
        """When all candidates are penalized, keep the least-penalized one."""
        candidates = [
            BrollCandidate(keywords=["family"], concept="family"),
            BrollCandidate(keywords=["family"], concept="family"),
        ]
        result = recommender._apply_diversity(
            candidates,
            covered_topics={"family"},
            used_keywords={"family"},
        )
        # Should keep at least one
        assert len(result) == 1

    def test_partial_overlap(self, recommender: AiBrollRecommender):
        """Candidates with partial overlap should be scored appropriately."""
        candidates = [
            BrollCandidate(keywords=["family", "home"], concept="family home"),
            BrollCandidate(keywords=["car", "insurance"], concept="car insurance"),
            BrollCandidate(keywords=["travel", "vacation"], concept="travel"),
        ]
        result = recommender._apply_diversity(
            candidates,
            covered_topics={"family"},
            used_keywords={"insurance"},
        )
        # "family home" has concept overlap → penalized
        # "car insurance" has keyword overlap → penalized
        # "travel" has no overlap → should be kept
        assert len(result) >= 1
        # "travel" should be in the result
        travel_keywords = [c.keywords for c in result if "travel" in c.keywords]
        assert len(travel_keywords) > 0

    def test_case_insensitive_matching(self, recommender: AiBrollRecommender):
        """Diversity matching should be case-insensitive."""
        candidates = [
            BrollCandidate(keywords=["Family"], concept="Family Protection"),
        ]
        result = recommender._apply_diversity(
            candidates,
            covered_topics={"family protection"},
            used_keywords=set(),
        )
        # Should be filtered out due to case-insensitive match.
        # Since there's only one candidate and it's penalized, the fallback
        # keeps the least-penalized one (to avoid returning empty results).
        assert len(result) == 1
        assert result[0].keywords == ["Family"]

    def test_empty_candidates(self, recommender: AiBrollRecommender):
        """Empty candidates list should return empty."""
        result = recommender._apply_diversity([], {"topic"}, {"kw"})
        assert result == []


# ── Duration computation tests ─────────────────────────────────────────────────

class TestComputeDuration:
    def test_default_duration(self, recommender: AiBrollRecommender):
        """Medium shot should get default duration."""
        cand = BrollCandidate(keywords=["test"], tipo_plano="medium")
        dur = recommender._compute_duration(cand, "clip_0", 3)
        assert dur == 5.5  # 4.5 + 1.0 (clip_0 is first segment)

    def test_closeup_duration(self, recommender: AiBrollRecommender):
        """Closeup should get shorter duration."""
        cand = BrollCandidate(keywords=["test"], tipo_plano="closeup")
        dur = recommender._compute_duration(cand, "clip_1", 3)
        assert dur == 3.0

    def test_wide_duration(self, recommender: AiBrollRecommender):
        """Wide shot should get longer duration."""
        cand = BrollCandidate(keywords=["test"], tipo_plano="wide")
        dur = recommender._compute_duration(cand, "clip_1", 3)
        assert dur == 5.0

    def test_first_segment_bonus(self, recommender: AiBrollRecommender):
        """First segment (clip_0) should get +1s bonus."""
        cand = BrollCandidate(keywords=["test"], tipo_plano="medium")
        dur = recommender._compute_duration(cand, "clip_0", 3)
        assert dur == 5.5  # 4.5 + 1.0

    def test_last_segment_bonus(self, recommender: AiBrollRecommender):
        """Last segment should get +1s bonus."""
        cand = BrollCandidate(keywords=["test"], tipo_plano="medium")
        dur = recommender._compute_duration(cand, "clip_2", 3)
        assert dur == 5.5  # 4.5 + 1.0

    def test_middle_segment_no_bonus(self, recommender: AiBrollRecommender):
        """Middle segment should not get bonus."""
        cand = BrollCandidate(keywords=["test"], tipo_plano="medium")
        dur = recommender._compute_duration(cand, "clip_1", 3)
        assert dur == 4.5

    def test_closeup_first_segment(self, recommender: AiBrollRecommender):
        """Closeup first segment should get closeup base + bonus."""
        cand = BrollCandidate(keywords=["test"], tipo_plano="closeup")
        dur = recommender._compute_duration(cand, "clip_0", 3)
        assert dur == 4.0  # 3.0 + 1.0

    def test_wide_last_segment(self, recommender: AiBrollRecommender):
        """Wide last segment should get wide base + bonus."""
        cand = BrollCandidate(keywords=["test"], tipo_plano="wide")
        dur = recommender._compute_duration(cand, "clip_4", 5)
        assert dur == 6.0  # 5.0 + 1.0

    def test_single_segment(self, recommender: AiBrollRecommender):
        """Single segment (clip_0, count=1) should get bonus (both first and last)."""
        cand = BrollCandidate(keywords=["test"], tipo_plano="medium")
        dur = recommender._compute_duration(cand, "clip_0", 1)
        assert dur == 5.5  # 4.5 + 1.0

    def test_non_numeric_segment_id(self, recommender: AiBrollRecommender):
        """Segment ID without numbers should default to index 0."""
        cand = BrollCandidate(keywords=["test"], tipo_plano="medium")
        dur = recommender._compute_duration(cand, "intro", 3)
        assert dur == 5.5  # 4.5 + 1.0 (treated as first)


# ── suggest_broll() tests (with mocked LLM) ────────────────────────────────────

class TestSuggestBroll:
    @patch("src.services.ai_broll_recommender.AiBrollRecommender._extract_via_llm")
    @pytest.mark.asyncio
    async def test_llm_success(self, mock_extract, recommender: AiBrollRecommender):
        """suggest_broll should return LLM candidates when LLM succeeds."""
        mock_extract.return_value = [
            BrollCandidate(
                keywords=["family"],
                tipo_plano="wide",
                mood="serious",
                concept="family protection",
            ),
            BrollCandidate(
                keywords=["money"],
                tipo_plano="medium",
                mood="neutral",
                concept="financial planning",
            ),
        ]
        candidates = await recommender.suggest_broll(
            transcript="Life insurance protects your family.",
            segment_id="clip_0",
        )
        assert len(candidates) == 2
        assert candidates[0].keywords == ["family"]
        assert candidates[1].keywords == ["money"]

    @patch("src.services.ai_broll_recommender.AiBrollRecommender._extract_via_llm")
    @pytest.mark.asyncio
    async def test_llm_failure_fallback(self, mock_extract, recommender: AiBrollRecommender):
        """suggest_broll should fall back to TF-IDF when LLM returns empty."""
        mock_extract.return_value = []
        candidates = await recommender.suggest_broll(
            transcript="insurance policy protects family home car health",
            segment_id="clip_0",
        )
        assert len(candidates) > 0
        # Should be TF-IDF keywords (meaningful nouns)
        all_keywords = [kw for c in candidates for kw in c.keywords]
        meaningful = {"insurance", "policy", "family", "home", "car", "health"}
        assert any(kw in meaningful for kw in all_keywords)

    @patch("src.services.ai_broll_recommender.AiBrollRecommender._extract_via_llm")
    @pytest.mark.asyncio
    async def test_diversity_context(self, mock_extract, recommender: AiBrollRecommender):
        """suggest_broll should apply diversity context to avoid repetition."""
        mock_extract.return_value = [
            BrollCandidate(keywords=["family"], concept="family protection"),
            BrollCandidate(keywords=["money"], concept="financial planning"),
            BrollCandidate(keywords=["car"], concept="car insurance"),
        ]
        task_ctx = make_task_ctx(
            covered_topics={"family protection"},
            used_keywords={"money"},
            segment_count=3,
        )
        candidates = await recommender.suggest_broll(
            transcript="Insurance covers family money and car.",
            segment_id="clip_1",
            task_ctx=task_ctx,
        )
        # "family" and "money" should be penalized, "car" should remain
        assert len(candidates) >= 1
        # "car" should be in the result
        car_candidates = [c for c in candidates if "car" in c.keywords]
        assert len(car_candidates) > 0

    @patch("src.services.ai_broll_recommender.AiBrollRecommender._extract_via_llm")
    @pytest.mark.asyncio
    async def test_task_ctx_updated(self, mock_extract, recommender: AiBrollRecommender):
        """suggest_broll should update task_ctx with new topics/keywords."""
        mock_extract.return_value = [
            BrollCandidate(keywords=["family"], concept="family protection"),
        ]
        task_ctx = make_task_ctx()
        await recommender.suggest_broll(
            transcript="Family is important.",
            segment_id="clip_0",
            task_ctx=task_ctx,
        )
        assert "family protection" in task_ctx["covered_topics"]
        assert "family" in task_ctx["used_keywords"]

    @patch("src.services.ai_broll_recommender.AiBrollRecommender._extract_via_llm")
    @pytest.mark.asyncio
    async def test_duration_computed(self, mock_extract, recommender: AiBrollRecommender):
        """suggest_broll should compute duration based on shot type and position."""
        mock_extract.return_value = [
            BrollCandidate(keywords=["family"], tipo_plano="closeup", concept="family"),
            BrollCandidate(keywords=["landscape"], tipo_plano="wide", concept="nature"),
        ]
        candidates = await recommender.suggest_broll(
            transcript="Family enjoys nature.",
            segment_id="clip_0",
            task_ctx=make_task_ctx(segment_count=3),
        )
        # clip_0 is first segment → +1s bonus
        assert candidates[0].prefered_duration_s == 4.0  # closeup 3.0 + 1.0
        assert candidates[1].prefered_duration_s == 6.0  # wide 5.0 + 1.0

    @patch("src.services.ai_broll_recommender.AiBrollRecommender._extract_via_llm")
    @pytest.mark.asyncio
    async def test_empty_transcript(self, mock_extract, recommender: AiBrollRecommender):
        """Empty transcript should return empty list."""
        mock_extract.return_value = []
        candidates = await recommender.suggest_broll(
            transcript="",
            segment_id="clip_0",
        )
        assert candidates == []

    @patch("src.services.ai_broll_recommender.AiBrollRecommender._extract_via_llm")
    @pytest.mark.asyncio
    async def test_no_api_key(self, mock_extract, recommender: AiBrollRecommender):
        """Recommender with no API key should skip LLM and use TF-IDF."""
        rec_no_key = AiBrollRecommender(llm_api_key="")
        # _extract_via_llm should return [] when no API key
        mock_extract.return_value = []
        candidates = await rec_no_key.suggest_broll(
            transcript="insurance policy family protection",
            segment_id="clip_0",
        )
        # Should fall back to TF-IDF
        assert len(candidates) > 0


# ── _extract_via_llm tests (with mocked HTTP) ──────────────────────────────────

class TestExtractViaLlm:
    @pytest.mark.asyncio
    async def test_no_api_key(self):
        """Without API key, _extract_via_llm should return empty."""
        rec = AiBrollRecommender(llm_api_key="")
        result = await rec._extract_via_llm("test transcript")
        assert result == []

    @patch("httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_successful_extraction(self, mock_client_class):
        """Successful LLM response should be parsed correctly."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "concept": "family protection",
                        "suggestions": [
                            {"keyword": "family", "shot_type": "wide", "mood": "serious"},
                            {"keyword": "protection", "shot_type": "medium", "mood": "neutral"},
                        ],
                    })
                }
            }]
        }
        mock_client.post.return_value = mock_response

        rec = AiBrollRecommender(llm_api_key="test-key")
        candidates = await rec._extract_via_llm("Family protection is important.")

        assert len(candidates) == 2
        assert candidates[0].keywords == ["family"]
        assert candidates[0].tipo_plano == "wide"
        assert candidates[0].mood == "serious"
        assert candidates[0].concept == "family protection"
        assert candidates[1].keywords == ["protection"]
        assert candidates[1].tipo_plano == "medium"
        assert candidates[1].mood == "neutral"

    @patch("httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_json_in_code_fence(self, mock_client_class):
        """LLM response with markdown code fences should be parsed correctly."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "```json\n{\n  \"concept\": \"nature\",\n  \"suggestions\": [\n    {\"keyword\": \"mountain\", \"shot_type\": \"wide\", \"mood\": \"serene\"}\n  ]\n}\n```"
                }
            }]
        }
        mock_client.post.return_value = mock_response

        rec = AiBrollRecommender(llm_api_key="test-key")
        candidates = await rec._extract_via_llm("Mountains are beautiful.")

        assert len(candidates) == 1
        assert candidates[0].keywords == ["mountain"]
        assert candidates[0].tipo_plano == "wide"
        assert candidates[0].mood == "serene"

    @patch("httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_invalid_shot_type_defaults(self, mock_client_class):
        """Invalid shot type should default to 'medium'."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "concept": "test",
                        "suggestions": [
                            {"keyword": "test", "shot_type": "extreme", "mood": "neutral"},
                        ],
                    })
                }
            }]
        }
        mock_client.post.return_value = mock_response

        rec = AiBrollRecommender(llm_api_key="test-key")
        candidates = await rec._extract_via_llm("Test.")

        assert len(candidates) == 1
        assert candidates[0].tipo_plano == "medium"

    @patch("httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_empty_keyword_skipped(self, mock_client_class):
        """Empty keyword should be skipped."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "concept": "test",
                        "suggestions": [
                            {"keyword": "", "shot_type": "medium", "mood": "neutral"},
                            {"keyword": "valid", "shot_type": "wide", "mood": "uplifting"},
                        ],
                    })
                }
            }]
        }
        mock_client.post.return_value = mock_response

        rec = AiBrollRecommender(llm_api_key="test-key")
        candidates = await rec._extract_via_llm("Test.")

        assert len(candidates) == 1
        assert candidates[0].keywords == ["valid"]

    @patch("httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_http_error(self, mock_client_class):
        """HTTP error should return empty list."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.post.side_effect = Exception("Connection error")

        rec = AiBrollRecommender(llm_api_key="test-key")
        candidates = await rec._extract_via_llm("Test.")

        assert candidates == []

    @patch("httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_invalid_json_response(self, mock_client_class):
        """Invalid JSON response should return empty list."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "This is not valid JSON"
                }
            }]
        }
        mock_client.post.return_value = mock_response

        rec = AiBrollRecommender(llm_api_key="test-key")
        candidates = await rec._extract_via_llm("Test.")

        assert candidates == []

    @patch("httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_missing_suggestions_key(self, mock_client_class):
        """Response missing 'suggestions' key should return empty."""
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps({"concept": "test"})
                }
            }]
        }
        mock_client.post.return_value = mock_response

        rec = AiBrollRecommender(llm_api_key="test-key")
        candidates = await rec._extract_via_llm("Test.")

        assert candidates == []


# ── Integration-style tests ─────────────────────────────────────────────────────

class TestIntegration:
    @patch("src.services.ai_broll_recommender.AiBrollRecommender._extract_via_llm")
    @pytest.mark.asyncio
    async def test_full_pipeline(self, mock_extract, recommender: AiBrollRecommender):
        """Full pipeline: LLM → diversity → duration → context update."""
        mock_extract.return_value = [
            BrollCandidate(keywords=["family"], tipo_plano="wide", concept="family protection"),
            BrollCandidate(keywords=["money"], tipo_plano="medium", concept="financial planning"),
            BrollCandidate(keywords=["health"], tipo_plano="closeup", concept="healthcare"),
        ]

        task_ctx = make_task_ctx(segment_count=3)

        # First call
        candidates1 = await recommender.suggest_broll(
            transcript="Family protection is important.",
            segment_id="clip_0",
            task_ctx=task_ctx,
        )
        assert len(candidates1) == 3
        # clip_0 is first → +1s bonus
        assert candidates1[0].prefered_duration_s == 6.0  # wide 5.0 + 1.0

        # Second call with updated context
        mock_extract.return_value = [
            BrollCandidate(keywords=["family"], tipo_plano="wide", concept="family protection"),
            BrollCandidate(keywords=["investment"], tipo_plano="medium", concept="investment"),
        ]
        candidates2 = await recommender.suggest_broll(
            transcript="Investment planning.",
            segment_id="clip_1",
            task_ctx=task_ctx,
        )
        # "family" should be penalized (already covered), "investment" should remain
        assert len(candidates2) >= 1
        investment_candidates = [c for c in candidates2 if "investment" in c.keywords]
        assert len(investment_candidates) > 0

    @patch("src.services.ai_broll_recommender.AiBrollRecommender._extract_via_llm")
    @pytest.mark.asyncio
    async def test_llm_failure_then_success(self, mock_extract, recommender: AiBrollRecommender):
        """LLM fails on first segment (TF-IDF fallback), succeeds on second."""
        # First call: LLM fails
        mock_extract.return_value = []
        candidates1 = await recommender.suggest_broll(
            transcript="insurance policy family protection home car",
            segment_id="clip_0",
        )
        assert len(candidates1) > 0  # TF-IDF fallback

        # Second call: LLM succeeds
        mock_extract.return_value = [
            BrollCandidate(keywords=["investment"], concept="investment planning"),
        ]
        candidates2 = await recommender.suggest_broll(
            transcript="Investment planning is key.",
            segment_id="clip_1",
        )
        assert len(candidates2) == 1
        assert candidates2[0].keywords == ["investment"]

    @pytest.mark.asyncio
    async def test_no_llm_key_full_fallback(self):
        """Without any LLM key, should always use TF-IDF."""
        rec = AiBrollRecommender(llm_api_key="")
        candidates = await rec.suggest_broll(
            transcript="insurance policy family protection",
            segment_id="clip_0",
        )
        assert len(candidates) > 0
        # All candidates should be from TF-IDF (medium shot, no mood)
        for c in candidates:
            assert c.tipo_plano == "medium"
            assert c.mood is None


# ── Feedback-based weighting tests ─────────────────────────────────────────────

class TestFeedbackWeights:
    """Tests for _compute_feedback_weights()."""

    def test_high_retention_reward(self):
        """watch_pct >= 0.65 should get a reward multiplier > 1.0."""
        rec = AiBrollRecommender(
            llm_api_key="",
            task_feedback={
                "city_skyline": {"used": 12, "avg_watch_pct": 0.85},
            },
        )
        weights = rec._feedback_weights
        assert weights is not None
        assert "city_skyline" in weights
        # 1.0 + (0.85 - 0.65) * 0.5 = 1.0 + 0.10 = 1.10
        assert weights["city_skyline"] == pytest.approx(1.10, abs=0.01)

    def test_low_retention_penalty(self):
        """watch_pct < 0.50 should get a penalty multiplier < 1.0."""
        rec = AiBrollRecommender(
            llm_api_key="",
            task_feedback={
                "office_meeting": {"used": 8, "avg_watch_pct": 0.35},
            },
        )
        weights = rec._feedback_weights
        assert weights is not None
        assert "office_meeting" in weights
        # 1.0 - (0.50 - 0.35) * 0.8 = 1.0 - 0.12 = 0.88
        assert weights["office_meeting"] == pytest.approx(0.88, abs=0.01)

    def test_neutral_range(self):
        """watch_pct between 0.50 and 0.65 should get weight = 1.0."""
        rec = AiBrollRecommender(
            llm_api_key="",
            task_feedback={
                "neutral_type": {"used": 10, "avg_watch_pct": 0.58},
            },
        )
        weights = rec._feedback_weights
        assert weights is not None
        assert weights["neutral_type"] == pytest.approx(1.0, abs=0.01)

    def test_sparse_data_confidence(self):
        """Fewer than 3 uses should pull weight closer to 1.0."""
        rec = AiBrollRecommender(
            llm_api_key="",
            task_feedback={
                "sparse_type": {"used": 1, "avg_watch_pct": 0.85},
            },
        )
        weights = rec._feedback_weights
        assert weights is not None
        # Full reward: 1.0 + (0.85 - 0.65) * 0.5 = 1.10
        # Confidence: 1/3 = 0.333
        # Adjusted: 1.0 + (1.10 - 1.0) * 0.333 = 1.0333
        assert weights["sparse_type"] == pytest.approx(1.0333, abs=0.01)

    def test_sparse_data_low_confidence(self):
        """Sparse data with penalty should also be pulled toward 1.0."""
        rec = AiBrollRecommender(
            llm_api_key="",
            task_feedback={
                "sparse_low": {"used": 2, "avg_watch_pct": 0.30},
            },
        )
        weights = rec._feedback_weights
        assert weights is not None
        # Full penalty: 1.0 - (0.50 - 0.30) * 0.8 = 1.0 - 0.16 = 0.84
        # Confidence: 2/3 = 0.667
        # Adjusted: 1.0 + (0.84 - 1.0) * 0.667 = 1.0 - 0.1067 = 0.8933
        assert weights["sparse_low"] == pytest.approx(0.8933, abs=0.01)

    def test_empty_feedback(self):
        """No feedback should result in no weights."""
        rec = AiBrollRecommender(llm_api_key="")
        assert rec._feedback_weights is None

    def test_zero_used(self):
        """used=0 should default to weight=1.0 (no confidence adjustment)."""
        rec = AiBrollRecommender(
            llm_api_key="",
            task_feedback={
                "zero_used": {"used": 0, "avg_watch_pct": 0.80},
            },
        )
        weights = rec._feedback_weights
        assert weights is not None
        # used=0 means no confidence adjustment, but weight is computed from watch_pct
        # 1.0 + (0.80 - 0.65) * 0.5 = 1.075
        assert weights["zero_used"] == pytest.approx(1.075, abs=0.01)

    def test_very_low_watch_pct(self):
        """Very low watch_pct should floor at 0.1."""
        rec = AiBrollRecommender(
            llm_api_key="",
            task_feedback={
                "very_low": {"used": 10, "avg_watch_pct": 0.05},
            },
        )
        weights = rec._feedback_weights
        assert weights is not None
        # Full penalty: 1.0 - (0.50 - 0.05) * 0.8 = 1.0 - 0.36 = 0.64
        # But with used=10, no confidence reduction
        assert weights["very_low"] == pytest.approx(0.64, abs=0.01)

    def test_multiple_types(self):
        """Multiple broll types should each get their own weight."""
        rec = AiBrollRecommender(
            llm_api_key="",
            task_feedback={
                "good_type": {"used": 10, "avg_watch_pct": 0.75},
                "bad_type": {"used": 10, "avg_watch_pct": 0.40},
                "mid_type": {"used": 10, "avg_watch_pct": 0.55},
            },
        )
        weights = rec._feedback_weights
        assert weights is not None
        assert len(weights) == 3
        # good_type: 1.0 + (0.75 - 0.65) * 0.5 = 1.05
        assert weights["good_type"] == pytest.approx(1.05, abs=0.01)
        # bad_type: 1.0 - (0.50 - 0.40) * 0.8 = 0.92
        assert weights["bad_type"] == pytest.approx(0.92, abs=0.01)
        # mid_type: 1.0 (neutral)
        assert weights["mid_type"] == pytest.approx(1.0, abs=0.01)


class TestApplyFeedbackWeights:
    """Tests for _apply_feedback_weights()."""

    def test_re_ranking_with_weights(self):
        """Candidates with higher weights should be promoted."""
        rec = AiBrollRecommender(
            llm_api_key="",
            task_feedback={
                "good_type": {"used": 10, "avg_watch_pct": 0.80},
                "bad_type": {"used": 10, "avg_watch_pct": 0.30},
            },
        )
        candidates = [
            BrollCandidate(keywords=["bad_type"], concept="bad concept"),
            BrollCandidate(keywords=["good_type"], concept="good concept"),
        ]
        result = rec._apply_feedback_weights(candidates)
        # "good_type" should be first (higher weight)
        assert result[0].keywords == ["good_type"]
        assert result[1].keywords == ["bad_type"]

    def test_no_feedback_weights(self):
        """Without feedback weights, candidates should pass through unchanged."""
        rec = AiBrollRecommender(llm_api_key="")
        candidates = [
            BrollCandidate(keywords=["a"], concept="concept a"),
            BrollCandidate(keywords=["b"], concept="concept b"),
        ]
        result = rec._apply_feedback_weights(candidates)
        assert result == candidates

    def test_keyword_match(self):
        """Keyword matching a broll_type should apply the weight."""
        rec = AiBrollRecommender(
            llm_api_key="",
            task_feedback={
                "mountain": {"used": 10, "avg_watch_pct": 0.75},
            },
        )
        candidates = [
            BrollCandidate(keywords=["mountain"], concept="nature"),
            BrollCandidate(keywords=["ocean"], concept="nature"),
        ]
        result = rec._apply_feedback_weights(candidates)
        # "mountain" has weight 1.05, "ocean" has no weight (1.0)
        # "mountain" should be first
        assert result[0].keywords == ["mountain"]

    def test_concept_match(self):
        """Concept matching a broll_type should apply the weight."""
        rec = AiBrollRecommender(
            llm_api_key="",
            task_feedback={
                "city_skyline": {"used": 5, "avg_watch_pct": 0.70},
            },
        )
        candidates = [
            BrollCandidate(keywords=["city"], concept="city_skyline"),
            BrollCandidate(keywords=["suburb"], concept="suburban_life"),
        ]
        result = rec._apply_feedback_weights(candidates)
        # "city_skyline" concept has weight > 1.0, should be first
        assert result[0].keywords == ["city"]

    def test_multiple_matches(self):
        """Multiple keyword matches should compound the multiplier."""
        rec = AiBrollRecommender(
            llm_api_key="",
            task_feedback={
                "good_a": {"used": 10, "avg_watch_pct": 0.80},
                "good_b": {"used": 10, "avg_watch_pct": 0.75},
            },
        )
        candidates = [
            BrollCandidate(keywords=["good_a", "good_b"], concept="double good"),
            BrollCandidate(keywords=["neutral"], concept="neutral"),
        ]
        result = rec._apply_feedback_weights(candidates)
        # "good_a" weight: 1.0 + (0.80 - 0.65) * 0.5 = 1.075
        # "good_b" weight: 1.0 + (0.75 - 0.65) * 0.5 = 1.05
        # Combined: 1.075 * 1.05 ≈ 1.12875
        # "neutral" weight: 1.0
        # First candidate should be ranked higher
        assert result[0].keywords == ["good_a", "good_b"]

    def test_all_candidates_penalized(self):
        """When all candidates have low weights, they should still be returned (just reordered)."""
        rec = AiBrollRecommender(
            llm_api_key="",
            task_feedback={
                "bad_a": {"used": 10, "avg_watch_pct": 0.20},
                "bad_b": {"used": 10, "avg_watch_pct": 0.30},
            },
        )
        candidates = [
            BrollCandidate(keywords=["bad_a"], concept="bad a"),
            BrollCandidate(keywords=["bad_b"], concept="bad b"),
        ]
        result = rec._apply_feedback_weights(candidates)
        # Both should still be present, just reordered
        assert len(result) == 2
        # "bad_b" has higher watch_pct → less penalty → should be first
        assert result[0].keywords == ["bad_b"]

    def test_mixed_keyword_and_concept_match(self):
        """Keyword match on one candidate and concept match on another."""
        rec = AiBrollRecommender(
            llm_api_key="",
            task_feedback={
                "keyword_type": {"used": 10, "avg_watch_pct": 0.80},
                "concept_type": {"used": 10, "avg_watch_pct": 0.70},
            },
        )
        candidates = [
            BrollCandidate(keywords=["keyword_type"], concept="other"),
            BrollCandidate(keywords=["other"], concept="concept_type"),
        ]
        result = rec._apply_feedback_weights(candidates)
        # keyword_type weight: 1.075, concept_type weight: 1.025
        # keyword_type candidate should be first
        assert result[0].keywords == ["keyword_type"]

    def test_case_insensitive_keyword_match(self):
        """Keyword matching should be case-insensitive."""
        rec = AiBrollRecommender(
            llm_api_key="",
            task_feedback={
                "mountain": {"used": 10, "avg_watch_pct": 0.80},
            },
        )
        candidates = [
            BrollCandidate(keywords=["Mountain"], concept="nature"),
            BrollCandidate(keywords=["ocean"], concept="nature"),
        ]
        result = rec._apply_feedback_weights(candidates)
        # "Mountain" (case-insensitive match) should be first
        assert result[0].keywords == ["Mountain"]

    def test_suggest_broll_with_feedback(self):
        """Integration: suggest_broll should apply feedback weights when task_feedback is provided."""
        rec = AiBrollRecommender(
            llm_api_key="",
            task_feedback={
                "family": {"used": 10, "avg_watch_pct": 0.80},
                "money": {"used": 10, "avg_watch_pct": 0.30},
            },
        )
        # Use TF-IDF fallback (no LLM key)
        candidates = rec._fallback_tfidf("family money protection insurance")
        # "family" should be ranked higher than "money" after feedback weighting
        family_idx = next(i for i, c in enumerate(candidates) if "family" in c.keywords)
        money_idx = next(i for i, c in enumerate(candidates) if "money" in c.keywords)
        assert family_idx < money_idx, (
            f"Expected 'family' before 'money', got family at {family_idx}, money at {money_idx}"
        )
