"""
Tests for:
  1. Blockchain / NFT API (/nft/*)
  2. Advanced Analytics API (/analytics/advanced/*)
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_nft_ownership(token_id="tok_001"):
    from src.services.blockchain_nft import (
        BlockchainNetwork, NFTMetadata, NFTOwnership, NFTStatus,
    )
    meta = NFTMetadata(
        name="Awesome Clip",
        description="ViraClip generated",
        image_url="/api/clips/clip_001/thumbnail",
        video_url="/api/clips/clip_001/video",
        creator_address="0xABCD",
        creator_name="Alice",
        created_at=datetime.now().isoformat(),
        content_hash="0xdeadbeef",
        duration=30.0,
        resolution="1080p",
        virality_score=0.88,
        attributes=[{"trait_type": "Duration", "value": 30}],
    )
    return NFTOwnership(
        token_id=token_id,
        contract_address="0xCONTRACT",
        network=BlockchainNetwork.POLYGON,
        owner_address="0xABCD",
        creator_address="0xABCD",
        mint_transaction="0xTXHASH",
        minted_at=datetime.now().isoformat(),
        status=NFTStatus.MINTED,
        metadata=meta,
        royalty_percentage=5.0,
        sale_history=[],
    )


def _make_nft_details(token_id="tok_001"):
    return {
        "token_id": token_id,
        "network": "polygon",
        "contract_address": "0xCONTRACT",
        "owner": "0xABCD",
        "creator": "0xABCD",
        "status": "minted",
        "mint_transaction": "0xTXHASH",
        "minted_at": datetime.now().isoformat(),
        "royalty_percentage": 5.0,
        "metadata": {
            "name": "Awesome Clip",
            "description": "ViraClip generated",
            "image": "/api/clips/clip_001/thumbnail",
            "video": "/api/clips/clip_001/video",
            "content_hash": "0xdeadbeef",
            "duration": 30.0,
            "resolution": "1080p",
            "virality_score": 0.88,
            "attributes": [],
        },
        "sale_history": [],
    }


# ===========================================================================
# 1. NFT API
# ===========================================================================

class TestNFTAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.nft import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_connect_wallet_success(self):
        client = self._get_client()
        with patch(
            "src.services.blockchain_nft.BlockchainNFTService.connect_wallet",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/nft/wallet/connect", json={
                "wallet_address": "0xABCD1234",
                "network": "polygon",
                "signature": "sig123",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "connected")
        self.assertEqual(data["network"], "polygon")

    def test_connect_wallet_invalid_sig(self):
        client = self._get_client()
        with patch(
            "src.services.blockchain_nft.BlockchainNFTService.connect_wallet",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.post("/nft/wallet/connect", json={
                "wallet_address": "0xBAD",
                "network": "ethereum",
                "signature": "badsig",
            })
        self.assertEqual(resp.status_code, 400)

    def test_connect_wallet_invalid_network(self):
        client = self._get_client()
        resp = client.post("/nft/wallet/connect", json={
            "wallet_address": "0xABCD",
            "network": "dogecoin_forever",
            "signature": "sig",
        })
        self.assertEqual(resp.status_code, 400)

    def test_mint_nft_success(self):
        client = self._get_client()
        nft = _make_nft_ownership()
        with patch(
            "src.services.blockchain_nft.BlockchainNFTService.mint_nft",
            new_callable=AsyncMock,
            return_value=nft,
        ):
            resp = client.post("/nft/mint", json={
                "clip_id": "clip_001",
                "clip_path": "/app/storage/clips/clip_001.mp4",
                "network": "polygon",
                "royalty_percentage": 5.0,
                "metadata": {"title": "Awesome Clip", "virality_score": 0.88},
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "minted")
        self.assertEqual(data["network"], "polygon")
        self.assertIn("token_id", data)

    def test_mint_nft_no_wallet(self):
        client = self._get_client()
        with patch(
            "src.services.blockchain_nft.BlockchainNFTService.mint_nft",
            new_callable=AsyncMock,
            side_effect=ValueError("No wallet connected for user"),
        ):
            resp = client.post("/nft/mint", json={
                "clip_id": "clip_001",
                "clip_path": "/app/clips/c.mp4",
            })
        self.assertEqual(resp.status_code, 400)

    def test_get_nft_success(self):
        client = self._get_client()
        with patch(
            "src.services.blockchain_nft.BlockchainNFTService.get_nft_details",
            return_value=_make_nft_details(),
        ):
            resp = client.get("/nft/tok_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["nft"]["token_id"], "tok_001")

    def test_get_nft_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.blockchain_nft.BlockchainNFTService.get_nft_details",
            return_value=None,
        ):
            resp = client.get("/nft/missing")
        self.assertEqual(resp.status_code, 404)

    def test_get_certificate(self):
        client = self._get_client()
        cert = {
            "certificate_id": "CERT-tok_001",
            "token_id": "tok_001",
            "content_title": "Awesome Clip",
            "content_hash": "0xdeadbeef",
            "creator": "0xABCD",
            "owner": "0xABCD",
            "network": "polygon",
            "minted_at": datetime.now().isoformat(),
            "verified": True,
            "verification_method": "SHA-256 content hash on blockchain",
            "issued_at": datetime.now().isoformat(),
        }
        with patch(
            "src.services.blockchain_nft.BlockchainNFTService.generate_certificate",
            new_callable=AsyncMock,
            return_value=cert,
        ):
            resp = client.get("/nft/tok_001/certificate")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["certificate"]["verified"])

    def test_verify_ownership_true(self):
        client = self._get_client()
        with patch(
            "src.services.blockchain_nft.BlockchainNFTService.verify_ownership",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/nft/tok_001/verify?claimed_owner=0xABCD")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["verified"])

    def test_verify_ownership_false(self):
        client = self._get_client()
        with patch(
            "src.services.blockchain_nft.BlockchainNFTService.verify_ownership",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.post("/nft/tok_001/verify?claimed_owner=0xEVIL")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["verified"])

    def test_transfer_nft_success(self):
        client = self._get_client()
        with patch(
            "src.services.blockchain_nft.BlockchainNFTService.transfer_nft",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/nft/tok_001/transfer", json={
                "from_address": "0xABCD",
                "to_address": "0xEFGH",
                "transaction_hash": "0xTX999",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "transferred")
        self.assertEqual(resp.json()["new_owner"], "0xEFGH")

    def test_transfer_nft_failure(self):
        client = self._get_client()
        with patch(
            "src.services.blockchain_nft.BlockchainNFTService.transfer_nft",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.post("/nft/tok_001/transfer", json={
                "from_address": "0xWRONG",
                "to_address": "0xEFGH",
                "transaction_hash": "0xBAD",
            })
        self.assertEqual(resp.status_code, 400)

    def test_list_for_sale(self):
        client = self._get_client()
        with patch(
            "src.services.blockchain_nft.BlockchainNFTService.list_nft_for_sale",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/nft/tok_001/list", json={"price": 0.5, "currency": "ETH"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "listed")

    def test_list_for_sale_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.blockchain_nft.BlockchainNFTService.list_nft_for_sale",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.post("/nft/missing/list", json={"price": 1.0})
        self.assertEqual(resp.status_code, 404)

    def test_get_user_collection(self):
        client = self._get_client()
        mock_nfts = [{"token_id": "tok_001", "network": "polygon", "status": "minted"}]
        with patch(
            "src.services.blockchain_nft.BlockchainNFTService.get_user_nfts",
            return_value=mock_nfts,
        ):
            resp = client.get("/nft/user/collection")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_get_stats(self):
        client = self._get_client()
        stats = {
            "total_nfts_minted": 100,
            "total_users_with_nfts": 42,
            "by_network": {"polygon": 80, "ethereum": 20},
            "connected_wallets": 55,
            "avg_royalty_percentage": 5.2,
        }
        with patch(
            "src.services.blockchain_nft.BlockchainNFTService.get_blockchain_stats",
            return_value=stats,
        ):
            resp = client.get("/nft/stats/overview")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["stats"]["total_nfts_minted"], 100)

    def test_list_networks(self):
        client = self._get_client()
        resp = client.get("/nft/networks/list")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("polygon", resp.json()["networks"])
        self.assertIn("ethereum", resp.json()["networks"])


# ===========================================================================
# 2. Advanced Analytics API
# ===========================================================================

class TestAdvancedAnalyticsAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.advanced_analytics import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_record_clip_metrics(self):
        client = self._get_client()
        with patch(
            "src.services.advanced_analytics.AdvancedAnalyticsService.record_clip_performance",
        ):
            resp = client.post("/analytics/advanced/clips/record", json={
                "clip_id": "clip_001",
                "task_id": "task_001",
                "platform": "tiktok",
                "views": 10000,
                "likes": 500,
                "shares": 200,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "recorded")
        self.assertEqual(resp.json()["clip_id"], "clip_001")

    def test_get_clip_analytics(self):
        client = self._get_client()
        mock_data = {
            "total_clips": 5,
            "total_views": 50000,
            "total_likes": 2000,
            "total_shares": 800,
            "avg_engagement_rate": 7.5,
            "avg_completion_rate": 0.62,
            "top_performing_clips": [],
            "platform_breakdown": {"tiktok": {"total_views": 50000, "avg_engagement": 7.5, "clip_count": 5}},
        }
        with patch(
            "src.services.advanced_analytics.AdvancedAnalyticsService.get_clip_analytics",
            return_value=mock_data,
        ):
            resp = client.get("/analytics/advanced/clips?days=30")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["analytics"]["total_views"], 50000)

    def test_get_clip_analytics_filtered(self):
        client = self._get_client()
        with patch(
            "src.services.advanced_analytics.AdvancedAnalyticsService.get_clip_analytics",
            return_value={"total_clips": 1, "total_views": 5000},
        ):
            resp = client.get("/analytics/advanced/clips?clip_id=clip_001&task_id=task_001")
        self.assertEqual(resp.status_code, 200)

    def test_record_user_activity(self):
        client = self._get_client()
        with patch(
            "src.services.advanced_analytics.AdvancedAnalyticsService.record_user_activity",
        ):
            resp = client.post("/analytics/advanced/users/record", json={
                "user_id": "user_a",
                "activity_type": "video_processed",
                "metadata": {},
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "recorded")

    def test_get_user_analytics_aggregate(self):
        client = self._get_client()
        mock_data = {
            "total_active_users": 150,
            "total_videos_processed": 600,
            "total_clips_generated": 2400,
            "avg_clips_per_user": 16.0,
            "tier_distribution": {"free": 100, "pro": 50},
            "power_users": [{"user_id": "user_a", "videos": 50}],
            "retention_estimate": 72.3,
        }
        with patch(
            "src.services.advanced_analytics.AdvancedAnalyticsService.get_user_analytics",
            return_value=mock_data,
        ):
            resp = client.get("/analytics/advanced/users?days=30")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["analytics"]["total_active_users"], 150)

    def test_record_system_metrics(self):
        client = self._get_client()
        with patch(
            "src.services.advanced_analytics.AdvancedAnalyticsService.record_system_metrics",
        ):
            resp = client.post("/analytics/advanced/system/record", json={
                "task_completed": True,
                "niche": "education",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "recorded")

    def test_get_system_health(self):
        client = self._get_client()
        mock_health = {
            "period": "Last 7 days",
            "total_tasks_completed": 980,
            "total_tasks_failed": 20,
            "overall_success_rate": 98.0,
            "success_trend": "+1.5%",
            "daily_breakdown": [],
            "system_status": "healthy",
        }
        with patch(
            "src.services.advanced_analytics.AdvancedAnalyticsService.get_system_health_report",
            return_value=mock_health,
        ):
            resp = client.get("/analytics/advanced/system/health?days=7")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["report"]["system_status"], "healthy")

    def test_generate_report(self):
        client = self._get_client()
        mock_report = {
            "report_period": {"start": "2026-01-01", "end": "2026-01-31", "days": 30},
            "executive_summary": {"total_clips_created": 500},
            "clip_performance": {},
            "user_engagement": {},
            "system_health": {"system_status": "healthy"},
            "growth_metrics": {"trend": "up"},
            "recommendations": ["All metrics looking good!"],
        }
        with patch(
            "src.services.advanced_analytics.AdvancedAnalyticsService.generate_comprehensive_report",
            return_value=mock_report,
        ):
            resp = client.post("/analytics/advanced/report", json={
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("recommendations", data["report"])

    def test_export_report(self):
        client = self._get_client()
        mock_report = {"report_period": {}, "executive_summary": {}}
        mock_path = Path("/app/data/analytics/analytics_report_20260101_120000.json")
        with patch(
            "src.services.advanced_analytics.AdvancedAnalyticsService.generate_comprehensive_report",
            return_value=mock_report,
        ), patch(
            "src.services.advanced_analytics.AdvancedAnalyticsService.export_report_to_file",
            return_value=mock_path,
        ):
            resp = client.post("/analytics/advanced/report/export", json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "exported")
        self.assertIn("path", data)


if __name__ == "__main__":
    unittest.main()
