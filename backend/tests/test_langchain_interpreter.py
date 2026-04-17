"""
Tests for LangChain operations and Open Interpreter routes.
"""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app(*routers):
    app = FastAPI()
    for r in routers:
        app.include_router(r)
    return app


# ══════════════════════════════════════════════════════════════════════════════
# LangChain Service Unit Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestLangChainService(unittest.TestCase):

    def test_is_available_when_installed(self):
        from src.services.langchain_service import LangChainService
        svc = LangChainService()
        # Just verify it returns a bool without raising
        result = svc.is_available()
        self.assertIsInstance(result, bool)

    def test_get_info_structure(self):
        from src.services.langchain_service import LangChainService
        svc = LangChainService()
        info = svc.get_info()
        self.assertIn("available", info)
        self.assertIn("providers_configured", info)
        self.assertIn("chains", info)
        self.assertIsInstance(info["chains"], list)

    def test_fallback_virality_scoring(self):
        from src.services.langchain_service import _fallback_virality
        result = _fallback_virality("Stop everything you're doing right now", 20.0)
        self.assertIn("virality_score", result)
        self.assertIn("hook_quality", result)
        self.assertEqual(result["source"], "fallback")
        self.assertIsInstance(result["virality_score"], int)

    def test_fallback_virality_empty_transcript(self):
        from src.services.langchain_service import _fallback_virality
        result = _fallback_virality("", 15.0)
        self.assertGreaterEqual(result["virality_score"], 0)
        self.assertLessEqual(result["virality_score"], 100)

    def test_singleton(self):
        from src.services.langchain_service import get_langchain_service
        a = get_langchain_service()
        b = get_langchain_service()
        self.assertIs(a, b)


class TestLangChainServiceFallbacks(unittest.IsolatedAsyncioTestCase):

    async def test_analyze_virality_fallback_when_llm_unavailable(self):
        from src.services.langchain_service import analyze_virality_with_langchain
        with patch("src.services.langchain_service._get_chat_model",
                   side_effect=RuntimeError("No LLM")):
            result = await analyze_virality_with_langchain("This is amazing!", "tiktok", 15.0)
        self.assertIn("virality_score", result)
        self.assertEqual(result["source"], "fallback")

    async def test_generate_metadata_fallback(self):
        from src.services.langchain_service import generate_viral_metadata
        with patch("src.services.langchain_service._get_chat_model",
                   side_effect=RuntimeError("No LLM")):
            result = await generate_viral_metadata("Great cooking tutorial", "tiktok")
        self.assertIn("title", result)
        self.assertIn("hashtags", result)
        self.assertEqual(result["source"], "fallback")

    async def test_rewrite_hook_fallback(self):
        from src.services.langchain_service import rewrite_hook
        with patch("src.services.langchain_service._get_chat_model",
                   side_effect=RuntimeError("No LLM")):
            result = await rewrite_hook("So today I want to talk about", "tiktok")
        self.assertIn("rewritten_hook", result)
        self.assertEqual(result["source"], "fallback")

    async def test_analyze_virality_with_mock_llm(self):
        """When LLM raises, fallback score is returned."""
        from src.services.langchain_service import analyze_virality_with_langchain
        with patch("src.services.langchain_service._get_chat_model",
                   side_effect=RuntimeError("No LLM configured")):
            result = await analyze_virality_with_langchain("Stop scrolling", "tiktok", 15.0)
        self.assertIn("virality_score", result)
        self.assertEqual(result["source"], "fallback")
        self.assertIsInstance(result["virality_score"], int)


class TestViraClipChatChain(unittest.IsolatedAsyncioTestCase):

    async def test_chat_returns_fallback_when_llm_unavailable(self):
        from src.services.langchain_service import ViraClipChatChain
        chain = ViraClipChatChain()
        with patch("src.services.langchain_service._get_chat_model",
                   side_effect=RuntimeError("No LLM")):
            reply = await chain.chat("How do I make my video go viral?")
        self.assertIn("unavailable", reply.lower())

    def test_clear_history(self):
        from src.services.langchain_service import ViraClipChatChain
        chain = ViraClipChatChain()
        chain._history = [{"human": "hi", "ai": "hello"}]
        chain.clear_history()
        self.assertEqual(len(chain.get_history()), 0)

    def test_get_history_returns_copy(self):
        from src.services.langchain_service import ViraClipChatChain
        chain = ViraClipChatChain()
        chain._history = [{"human": "a", "ai": "b"}]
        history = chain.get_history()
        self.assertEqual(len(history), 1)


# ══════════════════════════════════════════════════════════════════════════════
# Open Interpreter Service Unit Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestNaturalLanguageParser(unittest.IsolatedAsyncioTestCase):

    async def test_keyword_parse_create_clips(self):
        from src.services.open_interpreter_service import NaturalLanguageParser, TaskIntent
        parser = NaturalLanguageParser()
        with patch.object(parser, "_parse_with_llm",
                          side_effect=RuntimeError("no llm")):
            result = await parser.parse("Create 5 viral clips from this video")
        self.assertEqual(result.intent, TaskIntent.CREATE_CLIPS)
        self.assertEqual(result.confidence, 0.5)

    async def test_keyword_parse_virality(self):
        from src.services.open_interpreter_service import NaturalLanguageParser, TaskIntent
        parser = NaturalLanguageParser()
        with patch.object(parser, "_parse_with_llm",
                          side_effect=RuntimeError("no llm")):
            result = await parser.parse("Analyze the virality score of my clip")
        self.assertEqual(result.intent, TaskIntent.ANALYZE_VIRALITY)

    async def test_keyword_parse_metadata(self):
        from src.services.open_interpreter_service import NaturalLanguageParser, TaskIntent
        parser = NaturalLanguageParser()
        with patch.object(parser, "_parse_with_llm",
                          side_effect=RuntimeError("no llm")):
            result = await parser.parse("Generate hashtags and title for my cooking video")
        self.assertEqual(result.intent, TaskIntent.GENERATE_METADATA)

    async def test_keyword_parse_hook(self):
        from src.services.open_interpreter_service import NaturalLanguageParser, TaskIntent
        parser = NaturalLanguageParser()
        with patch.object(parser, "_parse_with_llm",
                          side_effect=RuntimeError("no llm")):
            result = await parser.parse("Rewrite the hook to be more shocking")
        self.assertEqual(result.intent, TaskIntent.REWRITE_HOOK)

    async def test_keyword_parse_download(self):
        from src.services.open_interpreter_service import NaturalLanguageParser, TaskIntent
        parser = NaturalLanguageParser()
        with patch.object(parser, "_parse_with_llm",
                          side_effect=RuntimeError("no llm")):
            result = await parser.parse("Download this video https://youtube.com/watch?v=abc123")
        self.assertEqual(result.intent, TaskIntent.DOWNLOAD_VIDEO)
        self.assertIn("url", result.params)

    async def test_keyword_parse_search(self):
        from src.services.open_interpreter_service import NaturalLanguageParser, TaskIntent
        parser = NaturalLanguageParser()
        with patch.object(parser, "_parse_with_llm",
                          side_effect=RuntimeError("no llm")):
            result = await parser.parse("Search for clips about ocean sunsets")
        self.assertEqual(result.intent, TaskIntent.SEARCH_CLIPS)

    async def test_keyword_parse_unknown(self):
        from src.services.open_interpreter_service import NaturalLanguageParser, TaskIntent
        parser = NaturalLanguageParser()
        with patch.object(parser, "_parse_with_llm",
                          side_effect=RuntimeError("no llm")):
            result = await parser.parse("xyzzy frobnicator quux")
        self.assertEqual(result.intent, TaskIntent.UNKNOWN)

    def test_url_extraction(self):
        from src.services.open_interpreter_service import NaturalLanguageParser
        parser = NaturalLanguageParser()
        result = parser._extract_url("Please download https://youtube.com/watch?v=test123")
        self.assertEqual(result["url"], "https://youtube.com/watch?v=test123")

    def test_url_extraction_no_url(self):
        from src.services.open_interpreter_service import NaturalLanguageParser
        parser = NaturalLanguageParser()
        result = parser._extract_url("No URL here at all")
        self.assertEqual(result, {})


class TestOpenInterpreterService(unittest.IsolatedAsyncioTestCase):

    async def test_empty_prompt_returns_error(self):
        from src.services.open_interpreter_service import OpenInterpreterService
        svc = OpenInterpreterService()
        result = await svc.execute("")
        self.assertFalse(result.success)
        self.assertIn("empty prompt", result.errors)

    async def test_whitespace_prompt_returns_error(self):
        from src.services.open_interpreter_service import OpenInterpreterService
        svc = OpenInterpreterService()
        result = await svc.execute("   ")
        self.assertFalse(result.success)

    async def test_unknown_intent_returns_guidance(self):
        from src.services.open_interpreter_service import OpenInterpreterService, TaskIntent
        svc = OpenInterpreterService()
        # Force keyword fallback to unknown
        with patch.object(svc._parser, "_parse_with_llm",
                          side_effect=RuntimeError("no llm")):
            result = await svc.execute("zxcvbnm qwerty")
        self.assertFalse(result.success)
        self.assertTrue(any("unknown" in e for e in result.errors))

    async def test_virality_intent_dispatches(self):
        from src.services.open_interpreter_service import OpenInterpreterService
        from src.services.langchain_service import LangChainService
        svc = OpenInterpreterService()
        mock_result = {
            "virality_score": 75, "recommendation": "Add stronger hook",
            "source": "fallback"
        }
        with patch.object(svc._parser, "_parse_with_llm",
                          side_effect=RuntimeError("no llm")):
            with patch("src.services.open_interpreter_service.get_interpreter_service",
                       return_value=svc):
                with patch("src.services.langchain_service.LangChainService.analyze_virality",
                           new=AsyncMock(return_value=mock_result)):
                    result = await svc.execute(
                        "Analyze virality of: Stop scrolling, you need to see this!"
                    )
        self.assertEqual(result.intent, "analyze_virality")

    async def test_parse_only(self):
        from src.services.open_interpreter_service import OpenInterpreterService, TaskIntent
        svc = OpenInterpreterService()
        with patch.object(svc._parser, "_parse_with_llm",
                          side_effect=RuntimeError("no llm")):
            parsed = await svc.parse_only("Generate hashtags for my fitness video")
        self.assertEqual(parsed.intent, TaskIntent.GENERATE_METADATA)
        self.assertIsInstance(parsed.confidence, float)

    def test_is_available(self):
        from src.services.open_interpreter_service import OpenInterpreterService
        svc = OpenInterpreterService()
        result = svc.is_available()
        self.assertIsInstance(result, bool)

    def test_get_info_structure(self):
        from src.services.open_interpreter_service import OpenInterpreterService
        svc = OpenInterpreterService()
        info = svc.get_info()
        self.assertIn("available", info)
        self.assertIn("supported_intents", info)
        self.assertIn("example_prompts", info)
        self.assertGreater(len(info["example_prompts"]), 0)

    def test_singleton(self):
        from src.services.open_interpreter_service import get_interpreter_service
        a = get_interpreter_service()
        b = get_interpreter_service()
        self.assertIs(a, b)


class TestTaskDispatcher(unittest.IsolatedAsyncioTestCase):

    async def test_dispatch_metadata(self):
        from src.services.open_interpreter_service import ParsedTask, TaskDispatcher, TaskIntent
        from src.services.langchain_service import LangChainService
        dispatcher = TaskDispatcher()
        task = ParsedTask(
            intent=TaskIntent.GENERATE_METADATA,
            params={"transcript": "Amazing cooking tutorial", "platform": "tiktok"},
            raw_prompt="Generate metadata",
        )
        with patch("src.services.open_interpreter_service.get_interpreter_service"):
            with patch.object(
                LangChainService, "generate_metadata",
                new=AsyncMock(return_value={
                    "title": "Amazing Cook", "hashtags": ["food"],
                    "description": "test", "cta": "follow", "best_posting_time": "7pm",
                    "source": "fallback"
                })
            ):
                result = await dispatcher.dispatch(task)
        self.assertEqual(result.intent, "generate_metadata")
        self.assertTrue(result.success)

    async def test_dispatch_download_missing_url(self):
        from src.services.open_interpreter_service import ParsedTask, TaskDispatcher, TaskIntent
        dispatcher = TaskDispatcher()
        task = ParsedTask(
            intent=TaskIntent.DOWNLOAD_VIDEO,
            params={},
            raw_prompt="Download the video",
        )
        result = await dispatcher.dispatch(task)
        self.assertFalse(result.success)
        self.assertIn("missing url", result.errors)

    async def test_dispatch_create_clips_queues(self):
        from src.services.open_interpreter_service import ParsedTask, TaskDispatcher, TaskIntent
        dispatcher = TaskDispatcher()
        task = ParsedTask(
            intent=TaskIntent.CREATE_CLIPS,
            params={"url": "https://youtube.com/watch?v=abc", "n_clips": 5, "platform": "tiktok"},
            raw_prompt="Create 5 clips",
        )
        result = await dispatcher.dispatch(task)
        self.assertTrue(result.success)
        self.assertEqual(result.result["n_clips"], 5)

    async def test_dispatch_search_clips(self):
        from src.services.open_interpreter_service import ParsedTask, TaskDispatcher, TaskIntent
        dispatcher = TaskDispatcher()
        task = ParsedTask(
            intent=TaskIntent.SEARCH_CLIPS,
            params={"query": "ocean sunset", "modality": "visual"},
            raw_prompt="Search for ocean clips",
        )
        result = await dispatcher.dispatch(task)
        self.assertTrue(result.success)
        self.assertEqual(result.result["modality"], "visual")


# ══════════════════════════════════════════════════════════════════════════════
# LangChain API Routes
# ══════════════════════════════════════════════════════════════════════════════

class TestLangChainRoutes(unittest.TestCase):

    def setUp(self):
        from src.api.routes.langchain_ops import router, _sessions
        _sessions.clear()
        from fastapi import FastAPI
        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def _mock_svc(self):
        svc = MagicMock()
        svc.get_info = MagicMock(return_value={
            "available": True,
            "providers_configured": {"openai": True},
            "chains": ["virality_analysis"],
        })
        svc.analyze_virality = AsyncMock(return_value={
            "virality_score": 82, "hook_quality": 78, "source": "langchain"
        })
        svc.generate_metadata = AsyncMock(return_value={
            "title": "You won't believe this", "hashtags": ["fyp", "viral"],
            "description": "test", "cta": "Follow me!", "source": "langchain"
        })
        svc.rewrite_hook = AsyncMock(return_value={
            "rewritten_hook": "Stop everything you're doing...",
            "hook_type": "curiosity_gap",
            "retention_improvement": 25,
            "source": "langchain"
        })
        mock_session = MagicMock()
        mock_session.chat = AsyncMock(return_value="Great question! Here's my advice...")
        mock_session.get_history = MagicMock(return_value=[{"human": "hi", "ai": "hello"}])
        svc.new_chat_session = MagicMock(return_value=mock_session)
        return svc

    def test_get_info(self):
        with patch("src.api.routes.langchain_ops.get_langchain_service",
                   return_value=self._mock_svc()):
            resp = self.client.get("/langchain/info")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["available"])

    def test_analyze_virality(self):
        with patch("src.api.routes.langchain_ops.get_langchain_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/langchain/analyze/virality", json={
                "transcript": "Stop scrolling! You need to hear this today.",
                "platform": "tiktok",
                "duration": 15.0,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["virality_score"], 82)

    def test_analyze_virality_invalid_platform(self):
        resp = self.client.post("/langchain/analyze/virality", json={
            "transcript": "test",
            "platform": "facebook",
        })
        self.assertEqual(resp.status_code, 422)

    def test_generate_metadata(self):
        with patch("src.api.routes.langchain_ops.get_langchain_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/langchain/generate/metadata", json={
                "transcript": "I tried this crazy diet for 30 days...",
                "platform": "youtube_shorts",
                "niche": "health",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("hashtags", resp.json())

    def test_rewrite_hook(self):
        with patch("src.api.routes.langchain_ops.get_langchain_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/langchain/rewrite/hook", json={
                "hook_text": "So today I wanted to tell you about something",
                "platform": "tiktok",
                "content_type": "talking_head",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("rewritten_hook", resp.json())
        self.assertEqual(resp.json()["retention_improvement"], 25)

    def test_rewrite_hook_invalid_content_type(self):
        resp = self.client.post("/langchain/rewrite/hook", json={
            "hook_text": "test",
            "content_type": "magic_show",
        })
        self.assertEqual(resp.status_code, 422)

    def test_create_and_use_chat_session(self):
        with patch("src.api.routes.langchain_ops.get_langchain_service",
                   return_value=self._mock_svc()):
            # Create session
            resp = self.client.post("/langchain/chat/session",
                                    json={"session_id": "test_sess_1"})
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json()["created"])

            # Send message
            resp2 = self.client.post("/langchain/chat/message", json={
                "session_id": "test_sess_1",
                "message": "How do I make my video go viral?",
            })
            self.assertEqual(resp2.status_code, 200)
            self.assertEqual(resp2.json()["reply"], "Great question! Here's my advice...")

    def test_chat_message_missing_session(self):
        resp = self.client.post("/langchain/chat/message", json={
            "session_id": "nonexistent_session_xyz",
            "message": "Hello",
        })
        self.assertEqual(resp.status_code, 404)

    def test_get_chat_history(self):
        with patch("src.api.routes.langchain_ops.get_langchain_service",
                   return_value=self._mock_svc()):
            self.client.post("/langchain/chat/session",
                             json={"session_id": "hist_sess"})
            resp = self.client.get("/langchain/chat/session/hist_sess/history")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("history", resp.json())

    def test_delete_chat_session(self):
        with patch("src.api.routes.langchain_ops.get_langchain_service",
                   return_value=self._mock_svc()):
            self.client.post("/langchain/chat/session",
                             json={"session_id": "del_sess"})
            resp = self.client.delete("/langchain/chat/session/del_sess")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["deleted"])

    def test_delete_nonexistent_session(self):
        resp = self.client.delete("/langchain/chat/session/nope_xyz")
        self.assertEqual(resp.status_code, 404)

    def test_get_history_nonexistent_session(self):
        resp = self.client.get("/langchain/chat/session/nope_xyz/history")
        self.assertEqual(resp.status_code, 404)


# ══════════════════════════════════════════════════════════════════════════════
# Open Interpreter API Routes
# ══════════════════════════════════════════════════════════════════════════════

class TestInterpreterRoutes(unittest.TestCase):

    def setUp(self):
        from src.api.routes.interpreter import router
        from fastapi import FastAPI
        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def _mock_svc(self):
        from src.services.open_interpreter_service import TaskResult
        svc = MagicMock()
        svc.get_info = MagicMock(return_value={
            "available": True,
            "supported_intents": ["create_clips", "analyze_virality"],
            "example_prompts": ["Create 5 clips from ..."],
        })
        svc.execute = AsyncMock(return_value=TaskResult(
            success=True,
            intent="analyze_virality",
            params={"platform": "tiktok"},
            result={"virality_score": 80},
            human_summary="Virality score: 80/100.",
        ))
        from src.services.open_interpreter_service import ParsedTask, TaskIntent
        svc.parse_only = AsyncMock(return_value=ParsedTask(
            intent=TaskIntent.ANALYZE_VIRALITY,
            params={"platform": "tiktok"},
            raw_prompt="Analyze virality",
            confidence=0.9,
            explanation="Detected virality analysis intent",
        ))
        return svc

    def test_get_info(self):
        with patch("src.api.routes.interpreter.get_interpreter_service",
                   return_value=self._mock_svc()):
            resp = self.client.get("/interpret/info")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["available"])
        self.assertIn("supported_intents", resp.json())
        self.assertIn("example_prompts", resp.json())

    def test_execute_success(self):
        with patch("src.api.routes.interpreter.get_interpreter_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/interpret/execute", json={
                "prompt": "Analyze virality of this text: Stop scrolling now!"
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["intent"], "analyze_virality")
        self.assertIn("summary", data)
        self.assertIn("result", data)

    def test_execute_empty_prompt(self):
        resp = self.client.post("/interpret/execute", json={"prompt": ""})
        self.assertEqual(resp.status_code, 422)

    def test_execute_too_long_prompt(self):
        resp = self.client.post("/interpret/execute", json={"prompt": "x" * 2001})
        self.assertEqual(resp.status_code, 422)

    def test_parse_only_success(self):
        with patch("src.api.routes.interpreter.get_interpreter_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/interpret/parse", json={
                "prompt": "Analyze virality of my clip"
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["intent"], "analyze_virality")
        self.assertIn("confidence", data)
        self.assertIn("explanation", data)
        self.assertEqual(data["confidence"], 0.9)

    def test_parse_only_empty_prompt(self):
        resp = self.client.post("/interpret/parse", json={"prompt": ""})
        self.assertEqual(resp.status_code, 422)

    def test_execute_service_error(self):
        svc = MagicMock()
        svc.execute = AsyncMock(side_effect=RuntimeError("service crashed"))
        with patch("src.api.routes.interpreter.get_interpreter_service",
                   return_value=svc):
            resp = self.client.post("/interpret/execute", json={
                "prompt": "Do something"
            })
        self.assertEqual(resp.status_code, 500)


if __name__ == "__main__":
    unittest.main()
