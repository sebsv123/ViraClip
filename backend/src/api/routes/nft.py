"""
Blockchain / NFT API — ViraClip

Endpoints for connecting wallets, minting clips as NFTs,
verifying ownership, transferring, and listing on marketplace.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...services.blockchain_nft import (
    BlockchainNetwork,
    BlockchainNFTService,
    get_blockchain_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/nft", tags=["nft"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class ConnectWalletRequest(BaseModel):
    wallet_address: str
    network: str = "polygon"   # ethereum | polygon | solana | base | arbitrum
    signature: str = ""        # wallet signature for verification


class MintNFTRequest(BaseModel):
    clip_id: str
    clip_path: str
    thumbnail_path: Optional[str] = None
    network: str = "polygon"
    royalty_percentage: float = 5.0
    metadata: Dict[str, Any] = {}


class TransferNFTRequest(BaseModel):
    from_address: str
    to_address: str
    transaction_hash: str


class ListForSaleRequest(BaseModel):
    price: float
    currency: str = "ETH"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_network(value: str) -> BlockchainNetwork:
    try:
        return BlockchainNetwork(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid network '{value}'. Choose: {[n.value for n in BlockchainNetwork]}",
        )


# ------------------------------------------------------------------
# Wallet
# ------------------------------------------------------------------

@router.post("/wallet/connect")
async def connect_wallet(request: Request, body: ConnectWalletRequest):
    """Connect a blockchain wallet to the current user account."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_blockchain_service()
    success = await svc.connect_wallet(
        user_id=user_id,
        wallet_address=body.wallet_address,
        network=_parse_network(body.network),
        signature=body.signature,
    )
    if not success:
        raise HTTPException(status_code=400, detail="Wallet signature verification failed")
    return {"status": "connected", "wallet": body.wallet_address, "network": body.network}


# ------------------------------------------------------------------
# Mint
# ------------------------------------------------------------------

@router.post("/mint")
async def mint_nft(request: Request, body: MintNFTRequest):
    """
    Mint a clip as an NFT on the specified blockchain network.
    The user must have a connected wallet for the chosen network.
    """
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_blockchain_service()
    clip_path = Path(body.clip_path)
    thumb_path = Path(body.thumbnail_path) if body.thumbnail_path else clip_path

    try:
        nft = await svc.mint_nft(
            user_id=user_id,
            clip_id=body.clip_id,
            clip_path=clip_path,
            thumbnail_path=thumb_path,
            metadata=body.metadata,
            network=_parse_network(body.network),
            royalty_percentage=body.royalty_percentage,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "minted",
        "token_id": nft.token_id,
        "network": nft.network.value,
        "contract_address": nft.contract_address,
        "mint_transaction": nft.mint_transaction,
        "minted_at": nft.minted_at,
        "royalty_percentage": nft.royalty_percentage,
    }


# ------------------------------------------------------------------
# Token operations
# ------------------------------------------------------------------

@router.get("/{token_id}")
def get_nft(token_id: str):
    """Get full NFT details including metadata, ownership, and sale history."""
    svc = get_blockchain_service()
    details = svc.get_nft_details(token_id)
    if details is None:
        raise HTTPException(status_code=404, detail=f"NFT '{token_id}' not found")
    return {"status": "success", "nft": details}


@router.get("/{token_id}/certificate")
async def get_certificate(token_id: str):
    """Generate an authenticity certificate for the NFT (SHA-256 content hash on chain)."""
    svc = get_blockchain_service()
    cert = await svc.generate_certificate(token_id)
    if cert is None:
        raise HTTPException(status_code=404, detail=f"NFT '{token_id}' not found")
    return {"status": "success", "certificate": cert}


@router.post("/{token_id}/verify")
async def verify_ownership(token_id: str, claimed_owner: str):
    """Verify that a given address owns this NFT on the blockchain."""
    svc = get_blockchain_service()
    is_owner = await svc.verify_ownership(token_id, claimed_owner)
    return {"token_id": token_id, "claimed_owner": claimed_owner, "verified": is_owner}


@router.post("/{token_id}/transfer")
async def transfer_nft(token_id: str, body: TransferNFTRequest):
    """Record an NFT transfer from one address to another."""
    svc = get_blockchain_service()
    success = await svc.transfer_nft(
        token_id=token_id,
        from_address=body.from_address,
        to_address=body.to_address,
        transaction_hash=body.transaction_hash,
    )
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Transfer failed: NFT not found or from_address is not the current owner",
        )
    return {"status": "transferred", "token_id": token_id, "new_owner": body.to_address}


@router.post("/{token_id}/list")
async def list_for_sale(token_id: str, body: ListForSaleRequest):
    """List an NFT for sale on the marketplace."""
    svc = get_blockchain_service()
    success = await svc.list_nft_for_sale(token_id, body.price, body.currency)
    if not success:
        raise HTTPException(status_code=404, detail=f"NFT '{token_id}' not found")
    return {"status": "listed", "token_id": token_id, "price": body.price, "currency": body.currency}


# ------------------------------------------------------------------
# User collection
# ------------------------------------------------------------------

@router.get("/user/collection")
def get_user_collection(request: Request):
    """Get all NFTs owned or created by the current user."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_blockchain_service()
    nfts = svc.get_user_nfts(user_id)
    return {"status": "success", "count": len(nfts), "nfts": nfts}


# ------------------------------------------------------------------
# Stats & metadata
# ------------------------------------------------------------------

@router.get("/stats/overview")
def get_stats():
    """Platform-wide NFT statistics: total minted, by network, connected wallets."""
    svc = get_blockchain_service()
    return {"status": "success", "stats": svc.get_blockchain_stats()}


@router.get("/networks/list")
def list_networks():
    """List all supported blockchain networks."""
    return {"networks": [n.value for n in BlockchainNetwork]}
