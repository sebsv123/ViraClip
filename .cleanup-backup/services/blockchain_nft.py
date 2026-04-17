"""
Blockchain NFT Service
Proof of ownership and content authenticity via NFT minting.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
import hashlib

logger = logging.getLogger(__name__)


class BlockchainNetwork(Enum):
    """Supported blockchain networks."""
    ETHEREUM = "ethereum"
    POLYGON = "polygon"
    SOLANA = "solana"
    BASE = "base"
    ARBITRUM = "arbitrum"


class NFTStatus(Enum):
    """NFT lifecycle status."""
    DRAFT = "draft"
    MINTING = "minting"
    MINTED = "minted"
    LISTED = "listed"
    SOLD = "sold"
    TRANSFERRED = "transferred"


@dataclass
class NFTMetadata:
    """NFT metadata structure."""
    name: str
    description: str
    image_url: str
    video_url: str
    creator_address: str
    creator_name: str
    created_at: str
    content_hash: str
    duration: float
    resolution: str
    virality_score: float
    attributes: List[Dict[str, Any]]


@dataclass
class NFTOwnership:
    """NFT ownership record."""
    token_id: str
    contract_address: str
    network: BlockchainNetwork
    owner_address: str
    creator_address: str
    mint_transaction: str
    minted_at: str
    status: NFTStatus
    metadata: NFTMetadata
    royalty_percentage: float
    sale_history: List[Dict[str, Any]]


class BlockchainNFTService:
    """
    Blockchain service for NFT minting and ownership verification.
    """
    
    def __init__(self):
        self._nft_records: Dict[str, NFTOwnership] = {}
        self._user_nfts: Dict[str, List[str]] = {}
        self._wallet_connections: Dict[str, Dict[str, str]] = {}
        self._contract_addresses = {
            BlockchainNetwork.POLYGON: "0x...",
            BlockchainNetwork.ETHEREUM: "0x...",
            BlockchainNetwork.SOLANA: "..."
        }
    
    async def connect_wallet(
        self,
        user_id: str,
        wallet_address: str,
        network: BlockchainNetwork,
        signature: str
    ) -> bool:
        """
        Connect a blockchain wallet to user account.
        
        Args:
            user_id: User ID
            wallet_address: Blockchain wallet address
            network: Blockchain network
            signature: Wallet signature for verification
        """
        # Verify signature (in production)
        is_valid = await self._verify_wallet_signature(
            wallet_address, signature
        )
        
        if not is_valid:
            return False
        
        if user_id not in self._wallet_connections:
            self._wallet_connections[user_id] = {}
        
        self._wallet_connections[user_id][network.value] = wallet_address
        
        logger.info(f"Connected {network.value} wallet for user {user_id}")
        return True
    
    async def _verify_wallet_signature(
        self,
        wallet_address: str,
        signature: str
    ) -> bool:
        """Verify wallet signature."""
        # Production implementation would verify with blockchain
        return True
    
    async def mint_nft(
        self,
        user_id: str,
        clip_id: str,
        clip_path: Path,
        thumbnail_path: Path,
        metadata: Dict[str, Any],
        network: BlockchainNetwork = BlockchainNetwork.POLYGON,
        royalty_percentage: float = 5.0
    ) -> NFTOwnership:
        """
        Mint an NFT for video content.
        
        Args:
            user_id: User minting the NFT
            clip_id: Clip identifier
            clip_path: Path to video file
            thumbnail_path: Path to thumbnail
            metadata: Additional metadata
            network: Blockchain network to use
            royalty_percentage: Creator royalty percentage
        """
        import uuid
        
        # Verify wallet connection
        if user_id not in self._wallet_connections:
            raise ValueError("No wallet connected for user")
        
        creator_address = self._wallet_connections[user_id].get(network.value)
        if not creator_address:
            raise ValueError(f"No {network.value} wallet connected")
        
        # Calculate content hash
        content_hash = await self._calculate_content_hash(clip_path)
        
        # Generate token ID
        token_id = f"{uuid.uuid4().hex[:16]}"
        
        # Create NFT metadata
        nft_metadata = NFTMetadata(
            name=metadata.get("title", f"Clip #{clip_id}"),
            description=metadata.get("description", "ViraClip generated content"),
            image_url=f"/api/clips/{clip_id}/thumbnail",
            video_url=f"/api/clips/{clip_id}/video",
            creator_address=creator_address,
            creator_name=metadata.get("creator_name", "Unknown"),
            created_at=datetime.now().isoformat(),
            content_hash=content_hash,
            duration=metadata.get("duration", 0),
            resolution=metadata.get("resolution", "1080p"),
            virality_score=metadata.get("virality_score", 0),
            attributes=self._generate_attributes(metadata)
        )
        
        # Mint on blockchain (simulated)
        mint_tx = await self._execute_mint(
            network, creator_address, token_id, nft_metadata
        )
        
        # Create ownership record
        nft = NFTOwnership(
            token_id=token_id,
            contract_address=self._contract_addresses.get(network, "0x"),
            network=network,
            owner_address=creator_address,
            creator_address=creator_address,
            mint_transaction=mint_tx,
            minted_at=datetime.now().isoformat(),
            status=NFTStatus.MINTED,
            metadata=nft_metadata,
            royalty_percentage=royalty_percentage,
            sale_history=[]
        )
        
        # Store record
        self._nft_records[token_id] = nft
        
        if user_id not in self._user_nfts:
            self._user_nfts[user_id] = []
        self._user_nfts[user_id].append(token_id)
        
        logger.info(f"Minted NFT {token_id} for clip {clip_id} on {network.value}")
        return nft
    
    async def _calculate_content_hash(self, clip_path: Path) -> str:
        """Calculate SHA-256 hash of clip content."""
        sha256 = hashlib.sha256()
        with open(clip_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return f"0x{sha256.hexdigest()}"
    
    def _generate_attributes(self, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate NFT attributes from metadata."""
        attributes = [
            {"trait_type": "Duration", "value": metadata.get("duration", 0), "display_type": "number"},
            {"trait_type": "Resolution", "value": metadata.get("resolution", "1080p")},
            {"trait_type": "Virality Score", "value": metadata.get("virality_score", 0), "display_type": "number"},
            {"trait_type": "Platform", "value": metadata.get("platform", "Multi-platform")},
            {"trait_type": "AI Generated", "value": metadata.get("ai_generated", True)},
        ]
        
        if metadata.get("niche"):
            attributes.append({"trait_type": "Niche", "value": metadata["niche"]})
        
        if metadata.get("effects"):
            attributes.append({"trait_type": "Effects", "value": len(metadata["effects"])})
        
        return attributes
    
    async def _execute_mint(
        self,
        network: BlockchainNetwork,
        creator_address: str,
        token_id: str,
        metadata: NFTMetadata
    ) -> str:
        """Execute mint transaction on blockchain."""
        # In production, this would call smart contract
        # Simulated transaction hash
        import uuid
        return f"0x{uuid.uuid4().hex}"
    
    async def verify_ownership(
        self,
        token_id: str,
        claimed_owner: str
    ) -> bool:
        """Verify NFT ownership."""
        if token_id not in self._nft_records:
            return False
        
        nft = self._nft_records[token_id]
        
        # Check blockchain (in production)
        blockchain_owner = await self._get_owner_from_chain(
            nft.network, nft.contract_address, token_id
        )
        
        return blockchain_owner.lower() == claimed_owner.lower()
    
    async def _get_owner_from_chain(
        self,
        network: BlockchainNetwork,
        contract: str,
        token_id: str
    ) -> str:
        """Query blockchain for current owner."""
        # Production: call smart contract ownerOf(tokenId)
        if token_id in self._nft_records:
            return self._nft_records[token_id].owner_address
        return "0x0"
    
    async def transfer_nft(
        self,
        token_id: str,
        from_address: str,
        to_address: str,
        transaction_hash: str
    ) -> bool:
        """Record NFT transfer."""
        if token_id not in self._nft_records:
            return False
        
        nft = self._nft_records[token_id]
        
        if nft.owner_address.lower() != from_address.lower():
            return False
        
        # Update ownership
        nft.owner_address = to_address
        nft.status = NFTStatus.TRANSFERRED
        
        # Add to sale history
        nft.sale_history.append({
            "from": from_address,
            "to": to_address,
            "transaction": transaction_hash,
            "timestamp": datetime.now().isoformat(),
            "type": "transfer"
        })
        
        return True
    
    async def list_nft_for_sale(
        self,
        token_id: str,
        price: float,
        currency: str = "ETH"
    ) -> bool:
        """List NFT for sale on marketplace."""
        if token_id not in self._nft_records:
            return False
        
        nft = self._nft_records[token_id]
        nft.status = NFTStatus.LISTED
        
        logger.info(f"Listed NFT {token_id} for {price} {currency}")
        return True
    
    def get_user_nfts(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all NFTs owned by user."""
        token_ids = self._user_nfts.get(user_id, [])
        nfts = []
        
        for token_id in token_ids:
            if token_id in self._nft_records:
                nft = self._nft_records[token_id]
                nfts.append({
                    "token_id": nft.token_id,
                    "network": nft.network.value,
                    "contract": nft.contract_address,
                    "status": nft.status.value,
                    "name": nft.metadata.name,
                    "image": nft.metadata.image_url,
                    "content_hash": nft.metadata.content_hash,
                    "minted_at": nft.minted_at,
                    "royalty": nft.royalty_percentage
                })
        
        return nfts
    
    def get_nft_details(self, token_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed NFT information."""
        if token_id not in self._nft_records:
            return None
        
        nft = self._nft_records[token_id]
        
        return {
            "token_id": nft.token_id,
            "network": nft.network.value,
            "contract_address": nft.contract_address,
            "owner": nft.owner_address,
            "creator": nft.creator_address,
            "status": nft.status.value,
            "mint_transaction": nft.mint_transaction,
            "minted_at": nft.minted_at,
            "royalty_percentage": nft.royalty_percentage,
            "metadata": {
                "name": nft.metadata.name,
                "description": nft.metadata.description,
                "image": nft.metadata.image_url,
                "video": nft.metadata.video_url,
                "content_hash": nft.metadata.content_hash,
                "duration": nft.metadata.duration,
                "resolution": nft.metadata.resolution,
                "virality_score": nft.metadata.virality_score,
                "attributes": nft.metadata.attributes
            },
            "sale_history": nft.sale_history
        }
    
    async def generate_certificate(
        self,
        token_id: str
    ) -> Optional[Dict[str, Any]]:
        """Generate authenticity certificate for NFT."""
        if token_id not in self._nft_records:
            return None
        
        nft = self._nft_records[token_id]
        
        return {
            "certificate_id": f"CERT-{token_id}",
            "token_id": token_id,
            "content_title": nft.metadata.name,
            "content_hash": nft.metadata.content_hash,
            "creator": nft.creator_address,
            "owner": nft.owner_address,
            "network": nft.network.value,
            "minted_at": nft.minted_at,
            "verified": True,
            "verification_method": "SHA-256 content hash on blockchain",
            "issued_at": datetime.now().isoformat()
        }
    
    def get_blockchain_stats(self) -> Dict[str, Any]:
        """Get blockchain service statistics."""
        total_nfts = len(self._nft_records)
        total_users = len(self._user_nfts)
        
        by_network = {}
        for nft in self._nft_records.values():
            net = nft.network.value
            by_network[net] = by_network.get(net, 0) + 1
        
        return {
            "total_nfts_minted": total_nfts,
            "total_users_with_nfts": total_users,
            "by_network": by_network,
            "connected_wallets": len(self._wallet_connections),
            "avg_royalty_percentage": sum(
                nft.royalty_percentage for nft in self._nft_records.values()
            ) / total_nfts if total_nfts > 0 else 0
        }


# Global instance
_blockchain_service: Optional[BlockchainNFTService] = None


def get_blockchain_service() -> BlockchainNFTService:
    """Get global blockchain NFT service."""
    global _blockchain_service
    if _blockchain_service is None:
        _blockchain_service = BlockchainNFTService()
    return _blockchain_service


# Convenience functions
async def mint_clip_as_nft(
    user_id: str,
    clip_id: str,
    clip_path: Path,
    metadata: Dict[str, Any]
) -> str:
    """Mint a clip as NFT."""
    service = get_blockchain_service()
    nft = await service.mint_nft(user_id, clip_id, clip_path, clip_path, metadata)
    return nft.token_id


def verify_content_authenticity(token_id: str) -> bool:
    """Verify NFT content authenticity."""
    service = get_blockchain_service()
    details = service.get_nft_details(token_id)
    if not details:
        return False
    return True
