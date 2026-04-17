"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { 
  Wallet, 
  ImageIcon, 
  ExternalLink, 
  Shield, 
  FileCheck,
  Copy,
  CheckCircle2,
  Loader2,
  ArrowRight,
  Coins,
  Gem
} from "lucide-react";

interface NFTDashboardProps {
  userId: string;
}

interface NFTItem {
  token_id: string;
  network: string;
  contract: string;
  status: string;
  name: string;
  image: string;
  content_hash: string;
  minted_at: string;
  royalty: number;
}

interface WalletConnection {
  network: string;
  address: string;
  connected: boolean;
}

export function NFTDashboard({ userId }: NFTDashboardProps) {
  const [nfts, setNfts] = useState<NFTItem[]>([]);
  const [wallets, setWallets] = useState<WalletConnection[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedNFT, setSelectedNFT] = useState<NFTItem | null>(null);
  const [copiedHash, setCopiedHash] = useState<string | null>(null);

  useEffect(() => {
    fetchNFTs();
    fetchWallets();
  }, [userId]);

  const fetchNFTs = async () => {
    try {
      const response = await fetch(`/api/blockchain/nfts?userId=${userId}`);
      const data = await response.json();
      setNfts(data);
    } catch (error) {
      console.error("Failed to fetch NFTs:", error);
    }
  };

  const fetchWallets = async () => {
    try {
      const response = await fetch(`/api/blockchain/wallets?userId=${userId}`);
      const data = await response.json();
      setWallets(data);
    } catch (error) {
      console.error("Failed to fetch wallets:", error);
    }
  };

  const connectWallet = async (network: string) => {
    setIsLoading(true);
    // Simulate wallet connection
    await new Promise((resolve) => setTimeout(resolve, 1500));
    
    setWallets([
      ...wallets,
      {
        network,
        address: `0x${Math.random().toString(16).slice(2, 14)}...`,
        connected: true,
      },
    ]);
    setIsLoading(false);
  };

  const copyHash = (hash: string) => {
    navigator.clipboard.writeText(hash);
    setCopiedHash(hash);
    setTimeout(() => setCopiedHash(null), 2000);
  };

  const getNetworkColor = (network: string) => {
    const colors: Record<string, string> = {
      ethereum: "bg-blue-500",
      polygon: "bg-purple-500",
      solana: "bg-green-500",
      base: "bg-blue-600",
      arbitrum: "bg-blue-400",
    };
    return colors[network] || "bg-gray-500";
  };

  return (
    <div className="space-y-6 p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <Gem className="h-8 w-8 text-purple-500" />
            NFT Collection
          </h1>
          <p className="text-muted-foreground">
            Proof of ownership on the blockchain
          </p>
        </div>
        <Button disabled={isLoading}>
          {isLoading ? (
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
          ) : (
            <Coins className="h-4 w-4 mr-2" />
          )}
          Mint New NFT
        </Button>
      </div>

      {/* Wallet Connections */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Wallet className="h-5 w-5" />
            Connected Wallets
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-4">
            {wallets.length === 0 ? (
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  onClick={() => connectWallet("polygon")}
                  disabled={isLoading}
                >
                  Connect Polygon
                </Button>
                <Button
                  variant="outline"
                  onClick={() => connectWallet("ethereum")}
                  disabled={isLoading}
                >
                  Connect Ethereum
                </Button>
                <Button
                  variant="outline"
                  onClick={() => connectWallet("solana")}
                  disabled={isLoading}
                >
                  Connect Solana
                </Button>
              </div>
            ) : (
              wallets.map((wallet) => (
                <Badge
                  key={wallet.network}
                  variant="secondary"
                  className="flex items-center gap-2 px-3 py-2"
                >
                  <div className={`w-2 h-2 rounded-full ${getNetworkColor(wallet.network)}`} />
                  <span className="capitalize">{wallet.network}</span>
                  <span className="font-mono text-xs">{wallet.address}</span>
                </Badge>
              ))
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* NFT Grid */}
        <div className="lg:col-span-2">
          <h2 className="text-xl font-semibold mb-4">Your NFTs</h2>
          {nfts.length === 0 ? (
            <Card className="p-8 text-center">
              <ImageIcon className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
              <h3 className="text-lg font-semibold mb-2">No NFTs yet</h3>
              <p className="text-muted-foreground mb-4">
                Mint your first clip as an NFT to establish proof of ownership
              </p>
              <Button>Mint Your First NFT</Button>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {nfts.map((nft) => (
                <Card
                  key={nft.token_id}
                  className={`cursor-pointer transition-all ${
                    selectedNFT?.token_id === nft.token_id
                      ? "border-primary ring-2 ring-primary"
                      : "hover:border-primary/50"
                  }`}
                  onClick={() => setSelectedNFT(nft)}
                >
                  <CardContent className="p-4">
                    <div className="aspect-video bg-muted rounded-lg mb-3 overflow-hidden">
                      {nft.image ? (
                        <img
                          src={nft.image}
                          alt={nft.name}
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                          <ImageIcon className="h-8 w-8" />
                        </div>
                      )}
                    </div>
                    <div className="flex items-start justify-between">
                      <div>
                        <h3 className="font-semibold line-clamp-1">{nft.name}</h3>
                        <div className="flex items-center gap-2 mt-1">
                          <Badge variant="outline" className="text-xs capitalize">
                            {nft.network}
                          </Badge>
                          <Badge
                            variant={nft.status === "minted" ? "default" : "secondary"}
                            className="text-xs"
                          >
                            {nft.status}
                          </Badge>
                        </div>
                      </div>
                    </div>
                    <div className="mt-3 pt-3 border-t">
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-muted-foreground">Royalty</span>
                        <span>{nft.royalty}%</span>
                      </div>
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-muted-foreground">Minted</span>
                        <span>
                          {new Date(nft.minted_at).toLocaleDateString()}
                        </span>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>

        {/* NFT Details */}
        <div>
          {selectedNFT ? (
            <Card className="sticky top-4">
              <CardHeader>
                <CardTitle>NFT Details</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="aspect-video bg-muted rounded-lg overflow-hidden">
                  {selectedNFT.image ? (
                    <img
                      src={selectedNFT.image}
                      alt={selectedNFT.name}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                      <ImageIcon className="h-12 w-12" />
                    </div>
                  )}
                </div>

                <div>
                  <h3 className="font-semibold text-lg">{selectedNFT.name}</h3>
                  <div className="flex items-center gap-2 mt-1">
                    <Badge className={`${getNetworkColor(selectedNFT.network)} text-white`}>
                      {selectedNFT.network}
                    </Badge>
                    <Badge variant="outline">{selectedNFT.status}</Badge>
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="flex items-center justify-between p-3 bg-muted rounded-lg">
                    <div className="flex items-center gap-2">
                      <Shield className="h-4 w-4 text-green-500" />
                      <span className="text-sm font-medium">Content Hash</span>
                    </div>
                    <button
                      onClick={() => copyHash(selectedNFT.content_hash)}
                      className="flex items-center gap-1 text-sm text-muted-foreground hover:text-primary"
                    >
                      {copiedHash === selectedNFT.content_hash ? (
                        <>
                          <CheckCircle2 className="h-4 w-4 text-green-500" />
                          Copied
                        </>
                      ) : (
                        <>
                          <Copy className="h-4 w-4" />
                          {selectedNFT.content_hash.slice(0, 10)}...
                        </>
                      )}
                    </button>
                  </div>

                  <div className="flex items-center justify-between p-3 bg-muted rounded-lg">
                    <div className="flex items-center gap-2">
                      <FileCheck className="h-4 w-4 text-blue-500" />
                      <span className="text-sm font-medium">Contract</span>
                    </div>
                    <a
                      href={`https://polygonscan.com/address/${selectedNFT.contract}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 text-sm text-muted-foreground hover:text-primary"
                    >
                      {selectedNFT.contract.slice(0, 8)}...
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  </div>

                  <div className="flex items-center justify-between p-3 bg-muted rounded-lg">
                    <div className="flex items-center gap-2">
                      <Coins className="h-4 w-4 text-yellow-500" />
                      <span className="text-sm font-medium">Creator Royalty</span>
                    </div>
                    <span className="text-sm">{selectedNFT.royalty}%</span>
                  </div>
                </div>

                <div className="pt-4 space-y-2">
                  <Button className="w-full">
                    <ExternalLink className="h-4 w-4 mr-2" />
                    View on Marketplace
                  </Button>
                  <Button variant="outline" className="w-full">
                    <FileCheck className="h-4 w-4 mr-2" />
                    Download Certificate
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : (
            <Card className="p-8 text-center">
              <Gem className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
              <p className="text-muted-foreground">
                Select an NFT to view details
              </p>
            </Card>
          )}
        </div>
      </div>

      {/* Info Section */}
      <Card className="bg-gradient-to-r from-purple-600 to-blue-600 text-white">
        <CardContent className="p-6">
          <div className="flex items-start gap-4">
            <div className="p-3 bg-white/20 rounded-lg">
              <Shield className="h-6 w-6" />
            </div>
            <div>
              <h3 className="text-lg font-semibold mb-2">
                Blockchain-Verified Ownership
              </h3>
              <p className="text-white/80 text-sm mb-4">
                Your clips are minted as NFTs, providing immutable proof of
                ownership and content authenticity. Each NFT includes a SHA-256
                content hash, ensuring your work cannot be forged.
              </p>
              <div className="flex gap-4 text-sm">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4" />
                  <span>Content Authenticity</span>
                </div>
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4" />
                  <span>Creator Royalties</span>
                </div>
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4" />
                  <span>Transferable Rights</span>
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
