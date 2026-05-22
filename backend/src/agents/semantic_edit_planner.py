"""
SemanticEditPlanner — Word-level B-roll and SFX cue generation.

Two-layer pipeline:
  Layer 1: Instant keyword heuristic (no API, <10ms, always runs)
  Layer 2: Groq semantic pass (one batch request per clip, ~1.5s)

Output: SemanticEditPlan with precise timestamps for B-roll insertion
and SFX placement tied to the exact word that triggered them.
"""
from __future__ import annotations

import asyncio
import base64
import glob
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class BrollCue:
    timestamp: float        # seconds from clip start — when to begin overlay
    keyword: str            # Pexels/Pixabay search term (English)
    duration: float         # overlay length in seconds (2-5s)
    trigger_phrase: str     # the spoken text that triggered this cue
    confidence: float       # 0-1


@dataclass
class SfxCue:
    timestamp: float        # seconds from clip start — when to fire SFX
    sfx_type: str           # key from SoundDesignService.VIRAL_SOUND_MAP
    trigger_word: str       # the word that triggered this cue
    intensity: float        # 0.3-1.0


@dataclass
class ZoomCue:
    timestamp: float    # seconds from clip start — when to apply zoom punch
    factor: float       # zoom scale factor (1.05-1.15)
    duration: float     # zoom animation duration in seconds (0.3-0.6)
    reason: str         # "excited_expression" | "high_energy" | "surprise"
    confidence: float   # 0-1


@dataclass
class SemanticEditPlan:
    broll_cues: List[BrollCue] = field(default_factory=list)  # max 3 per clip
    sfx_cues:   List[SfxCue]   = field(default_factory=list)  # max 4 per clip
    zoom_cues:  List[ZoomCue]  = field(default_factory=list)  # max 4 per clip (vision)
    source: str = "heuristic"                                  # "groq" | "vision_groq" | "vision_ollama"


# ── Heuristic lookup tables (ES + EN) ────────────────────────────────────────

_MONEY_RE   = re.compile(r"(?:\$|€|£|\d+[kKmM]|\d{3,})", re.IGNORECASE)
_NUMBER_BIG = re.compile(r"\b\d{3,}\b")

_PLACE_MAP: Dict[str, str] = {
    "ciudad": "modern city skyline", "city": "modern city skyline",
    "casa": "home interior", "home": "home interior", "house": "home interior",
    "oficina": "office workspace", "office": "office workspace",
    "playa": "beach ocean", "beach": "beach ocean",
    "montaña": "mountain landscape", "mountain": "mountain landscape",
    "calle": "street urban", "street": "street urban",
    "restaurante": "restaurant dining", "restaurant": "restaurant dining",
    "aeropuerto": "airport travel", "airport": "airport travel",
    "gimnasio": "gym workout", "gym": "gym workout",
    "hospital": "hospital medical", "escuela": "classroom school",
    "school": "classroom school", "universidad": "university campus",
    "university": "university campus",
}

_ACTION_MAP: Dict[str, str] = {
    "corr": "running athlete", "run": "running athlete",
    "construi": "construction building", "build": "construction building",
    "cocin": "cooking food", "cook": "cooking food",
    "entrenam": "workout training", "train": "workout training",
    "escrib": "writing desk", "write": "writing desk",
    "viaj": "travel adventure", "travel": "travel adventure",
    "vend": "sales deal", "sell": "sales deal",
    "invert": "investment chart", "invest": "investment chart",
    "programar": "coding laptop", "coding": "coding laptop",
    "diseñ": "graphic design", "design": "graphic design",
    "meditar": "meditation calm", "meditat": "meditation calm",
}

_ROLE_MAP: Dict[str, str] = {
    "médico": "doctor hospital", "doctor": "doctor hospital",
    "ceo": "business executive", "executive": "business executive",
    "atleta": "athlete sport", "athlete": "athlete sport",
    "empresario": "entrepreneur startup", "entrepreneur": "entrepreneur startup",
    "programador": "programmer coding", "developer": "programmer coding",
    "chef": "chef cooking kitchen",
    "abogado": "lawyer courtroom", "lawyer": "lawyer courtroom",
    "profesor": "teacher classroom", "teacher": "teacher classroom",
    "músico": "musician performance", "musician": "musician performance",
    "artista": "artist studio", "artist": "artist studio",
}

_OBJECT_MAP: Dict[str, str] = {
    "coche": "luxury car", "car": "luxury car", "auto": "luxury car",
    "ordenador": "laptop computer", "laptop": "laptop computer",
    "teléfono": "smartphone", "phone": "smartphone",
    "dinero": "cash money", "money": "cash money", "cash": "cash money",
    "libro": "book reading", "book": "book reading",
    "avión": "airplane flight", "plane": "airplane flight",
    "comida": "food meal", "food": "food meal",
    "café": "coffee cup", "coffee": "coffee cup",
    "música": "music studio", "music": "music studio",
}

_VISUAL_LOOKUPS = [_PLACE_MAP, _ACTION_MAP, _ROLE_MAP, _OBJECT_MAP]

# SFX trigger sets: (fragment_set, sfx_type, intensity)
# Order matters — first match wins. Magic reveal goes BEFORE generic
# pattern_interrupt so superlatives produce a magical chime, not a glitch.
_SFX_TRIGGERS: List[tuple] = [
    (
        # Magic reveal — superlatives / "never seen before" moments
        {"increíble", "incredible", "asombroso", "impresionante",
         "sorprendente", "unbelievable", "never seen", "jamás visto",
         "por primera vez", "first time", "flipante", "alucinante"},
        "magic_reveal", 0.92,
    ),
    (
        {"secreto", "secret", "verdad", "truth", "real", "descubrí", "discovered",
         "nunca", "never", "jamás", "revelación", "reveal", "expuesto", "exposed",
         "clave", "key", "razón", "reason"},
        "insight_reveal", 0.85,
    ),
    (
        {"por qué", "why", "sabes", "knew", "sabías", "imagina", "imagine",
         "qué pasaría", "what if", "cómo", "how", "cuál", "which"},
        "curiosity_gap", 0.75,
    ),
    (
        # Pattern interrupt — contradiction / surprise (without superlative)
        {"espera", "wait", "para", "stop", "mentira", "lie", "falso", "wrong",
         "error", "mistake", "equivocado", "sorpresa", "surprise",
         "imposible", "impossible"},
        "pattern_interrupt", 0.80,
    ),
    (
        {"pero", "sin embargo", "however", "aunque", "though",
         "hay más", "more", "además", "also", "todavía", "still",
         "lo que nadie", "nobody", "nadie sabe"},
        "cliffhanger", 0.55,
    ),
    (
        {"entonces", "así que", "so", "por eso", "that's why",
         "finalmente", "finally", "ahora", "now", "resultado", "result"},
        "transition", 0.60,
    ),
]

_VALID_SFX = {
    # Original hook-types
    "insight_reveal", "curiosity_gap", "pattern_interrupt",
    "cliffhanger", "emphasis_word", "scroll_stop", "transition",
    # Phase 3 contextual types
    "magic_reveal", "whoosh_zoom", "pop_broll", "riser_pre_reveal",
    "camera_shutter", "bass_drop", "notification", "glitch_burst",
}

# Timing constants
_BROLL_HOOK_GUARD = 2.0     # no B-roll in first 2s (protect hook)
_BROLL_CTA_GUARD  = 2.0     # no B-roll in last 2s
_BROLL_MIN_GAP    = MIN_GAP_BETWEEN_OVERLAYS_S  # minimum gap between B-rolls
_BROLL_MAX        = 3       # max B-rolls per clip
_SFX_MIN_GAP      = 1.5     # minimum gap between SFX
_SFX_MAX          = 8       # max SFX per clip (raised for contextual rules)
_WINDOW_S         = 5.0     # Groq analysis window size


# Vision constants
_VISION_MODEL_GROQ  = "meta-llama/llama-4-scout-17b-16e-instruct"
_VISION_INTERVAL_S  = 4.0   # 1 frame every N seconds
_VISION_MAX_FRAMES  = 12    # hard cap to stay within token limits
_VISION_TIMEOUT_S   = 15.0  # total timeout for Groq Vision call
_ZOOM_MAX           = 4     # max zoom cues per clip
_ZOOM_MIN_GAP       = 4.0   # min seconds between zoom cues


from ..domains.broll.broll_config import (
    MIN_OVERLAY_DURATION_S,
    MIN_GAP_BETWEEN_OVERLAYS_S,
)

# ── Shared minimum overlay duration (from canonical broll_config) ────────────
BROLL_MIN_OVERLAY_DURATION_S = MIN_OVERLAY_DURATION_S


# ── GENERIC CONCEPTS BLACKLIST ────────────────────────────────────────────────
# Concepts that are too generic, motivational, abstract, or not clearly tied to
# the spoken topic. These are rejected at every stage of the pipeline.
# Every rejected concept is logged with a reason code.
_GENERIC_CONCEPTS: set = {
    # ── Motivational / abstract / self-help ──
    "success", "achievement", "determination", "motivation", "inspiration",
    "dream", "goal", "passion", "excellence", "greatness", "success achievement",
    "winner", "winning", "champion", "victory", "triumph", "conquer",
    "overcome", "perseverance", "persistence", "resilience", "grit",
    "mindset", "growth mindset", "positive thinking", "positive attitude",
    "self improvement", "self help", "personal development", "personal growth",
    "empowerment", "empower", "believe", "belief", "faith",
    "courage", "bravery", "confidence", "self confidence",
    "potential", "unlock potential", "reach potential", "fulfillment",
    "transformation", "life changing", "breakthrough", "break through",
    "limitless", "unlimited", "infinite", "endless possibilities",
    "abundance", "prosperity", "wealth mindset", "millionaire mindset",
    "hustle", "grind", "work hard", "never give up", "keep going",
    "rise", "rise up", "stand out", "shine", "sparkle",
    "miracle", "magic", "extraordinary", "remarkable", "unbelievable",
    "best version", "best self", "new you", "new beginning", "fresh start",
    "second chance", "opportunity", "possibility", "possibilities",
    "vision", "vision board", "manifest", "manifestation", "law of attraction",
    "destiny", "fate", "purpose", "calling", "mission",
    "legacy", "impact", "make a difference", "change the world",
    "inspirational", "motivational", "uplifting", "encouraging",
    "sunrise", "sunset", "mountains", "sunrise mountains", "nature landscape",
    "ocean view", "beach sunset", "mountain top", "climbing mountain",
    "horizon", "sky", "clouds", "sunshine", "sunlight",
    # ── Generic people / objects ──
    "person", "people", "camera", "man", "woman", "child", "group",
    "hands", "face", "smile", "laugh", "celebration",
    "crowd", "audience", "spectator", "onlooker", "bystander",
    "portrait", "selfie", "photo", "photograph", "picture",
    "silhouette", "shadow", "reflection", "mirror",
    "handshake", "hand", "finger", "arm", "leg", "foot",
    "eye", "eyes", "look", "stare", "gaze",
    "walking", "running", "jumping", "dancing", "sitting", "standing",
    # ── Generic tech / digital ──
    "technology", "innovation", "digital", "future", "modern",
    "tech", "high tech", "cutting edge", "state of the art",
    "artificial intelligence", "ai", "machine learning", "deep learning",
    "robot", "robotics", "automation", "automated",
    "computer", "laptop", "screen", "monitor", "display",
    "keyboard", "mouse", "typing", "coding", "programming",
    "software", "hardware", "chip", "processor", "circuit",
    "data", "big data", "cloud", "cloud computing", "server",
    "network", "internet", "web", "online", "digital world",
    "cyber", "cybersecurity", "encryption", "blockchain", "crypto",
    "virtual", "virtual reality", "vr", "augmented reality", "ar",
    "metaverse", "digital transformation", "industry 4.0",
    "smart", "smartphone", "mobile", "app", "application",
    "innovation lab", "startup", "scale up", "disruption", "disruptive",
    # ── Generic business / corporate ──
    "business", "corporate", "professional", "teamwork", "leadership",
    "management", "manager", "executive", "ceo", "founder",
    "entrepreneur", "entrepreneurship", "startup culture",
    "strategy", "strategic", "planning", "business planning",
    "growth", "scaling", "expansion", "global", "worldwide",
    "enterprise", "organization", "company", "firm", "corporation",
    "boardroom", "board meeting", "shareholder", "stakeholder",
    "revenue", "profit", "profitability", "margin", "roi",
    "synergy", "leverage", "optimize", "streamline", "efficiency",
    "productivity", "performance", "results", "outcome",
    "solution", "solutions", "end to end", "turnkey",
    "consulting", "consultant", "advisor", "advisory",
    "networking", "network event", "business card", "coffee meeting",
    "pitch", "elevator pitch", "presentation", "slide deck",
    "deal", "partnership", "collaboration", "cooperation",
    "b2b", "b2c", "saas", "enterprise software",
    # ── Generic abstract concepts ──
    "concept", "idea", "solution", "change", "growth", "progress",
    "power", "strength", "freedom", "peace", "love", "hope",
    "future", "past", "present", "time", "moment",
    "life", "death", "birth", "beginning", "end",
    "world", "earth", "universe", "cosmos", "nature",
    "energy", "force", "spirit", "soul", "mind",
    "thought", "thinking", "knowledge", "wisdom", "intelligence",
    "truth", "honesty", "integrity", "justice", "fairness",
    "equality", "diversity", "inclusion", "belonging",
    "sustainability", "environment", "eco", "green", "renewable",
    "balance", "harmony", "unity", "togetherness", "solidarity",
    "quality", "value", "excellence", "perfection", "precision",
    "simplicity", "minimalism", "clarity", "focus", "awareness",
    "consciousness", "mindfulness", "meditation", "zen", "calm",
    "chaos", "order", "system", "process", "framework",
    "journey", "path", "road", "way", "direction",
    "secret", "mystery", "discovery", "exploration", "quest",
    "revolution", "evolution", "transformation", "shift", "paradigm",
    "advantage", "edge", "upper hand", "competitive edge",
    "insight", "wisdom", "lesson", "teaching", "learning",
    # ── Generic travel / lifestyle ──
    "travel", "adventure", "lifestyle", "luxury", "beautiful",
    "happy", "joy", "fun", "amazing", "wonderful",
    "vacation", "holiday", "getaway", "escape", "retreat",
    "explore", "exploration", "wanderlust", "journey", "trip",
    "destination", "paradise", "heaven", "bliss", "serenity",
    "relaxation", "relax", "chill", "chill out", "unwind",
    "weekend", "weekend getaway", "road trip", "summer", "winter",
    "spring", "autumn", "season", "weather", "climate",
    "sunny", "rainy", "snowy", "windy", "stormy",
    "cozy", "comfortable", "comfy", "snug", "warm",
    "delicious", "tasty", "yummy", "food", "cuisine",
    "fitness", "workout", "exercise", "gym", "yoga",
    "health", "wellness", "wellbeing", "self care", "selfcare",
    "beauty", "beautiful", "gorgeous", "stunning", "lovely",
    "fashion", "style", "trendy", "chic", "elegant",
    "shopping", "retail", "store", "mall", "boutique",
    "party", "celebration", "festival", "event", "gathering",
    "wedding", "marriage", "romance", "romantic", "love story",
    "family", "friends", "friendship", "community", "together",
    # ── Generic nature / scenery (unless transcript explicitly requires) ──
    "nature", "landscape", "scenery", "view", "panorama",
    "forest", "woods", "tree", "trees", "river", "lake",
    "ocean", "sea", "beach", "coast", "shore",
    "field", "meadow", "grass", "flower", "flowers",
    "garden", "park", "trail", "path", "waterfall",
    "rainbow", "stars", "moon", "night sky", "aurora",
    "desert", "canyon", "valley", "hill", "cliff",
    "island", "tropical", "palm tree", "coral reef",
    "animal", "wildlife", "bird", "butterfly", "dolphin",
    # ── Generic office / workspace (unless transcript explicitly requires) ──
    "office", "workspace", "desk", "cubicle", "open office",
    "meeting room", "conference room", "break room", "lobby",
    "reception", "receptionist", "secretary", "assistant",
    "water cooler", "coffee machine", "printer", "scanner",
    "filing cabinet", "filing", "paperwork", "paper", "documents",
    "stationery", "pen", "pencil", "notebook", "sticky note",
    "whiteboard", "bulletin board", "calendar", "planner",
    "briefcase", "suitcase", "bag", "backpack",
    "badge", "id card", "keycard", "access card",
    "headset", "headphones", "earpiece", "microphone",
    "phone call", "telephone", "landline", "voicemail",
    # ── Generic stock photo clichés ──
    "diverse group", "diverse team", "multi ethnic", "multicultural",
    "global team", "international team", "cross cultural",
    "young professional", "young entrepreneur", "millennial",
    "senior executive", "older professional", "grey hair",
    "business casual", "suit and tie", "formal wear",
    "tie", "suit", "blazer", "jacket", "uniform",
    "hard hat", "safety vest", "safety gear", "protective gear",
    "lab coat", "scrubs", "white coat", "surgical mask",
    "glasses", "spectacles", "sunglasses", "reading glasses",
    "coffee cup", "coffee mug", "tea cup", "water bottle",
    "smart casual", "dressed up", "dressed down",
    "office party", "team building", "corporate event",
    "award", "trophy", "medal", "ribbon", "certificate",
    "diploma", "degree", "graduation", "graduate",
    "hand shake", "handshake deal", "signing deal", "closing deal",
    "high five", "fist bump", "thumbs up", "ok sign",
    "pointing", "pointing finger", "pointing hand",
    "puzzle piece", "jigsaw", "lightbulb", "light bulb",
    "gears", "cogs", "machinery", "engine", "motor",
    "target", "bullseye", "dartboard", "arrow", "checkmark",
    "checklist", "clipboard", "to do list", "task list",
    "clock", "watch", "timer", "hourglass", "stopwatch",
    "globe", "world map", "map", "compass", "direction sign",
    "question mark", "exclamation mark", "info sign",
    "up arrow", "down arrow", "growth chart", "trend line",
    "pie chart", "bar chart", "line graph", "infographic",
    "placeholder", "mockup", "template", "sample",
    "generic", "stock photo", "royalty free", "shutterstock",
    # ── Generic abstract art / backgrounds ──
    "abstract", "abstract background", "geometric pattern",
    "colorful background", "gradient", "bokeh", "blur",
    "particle", "particles", "sparkle", "sparkles", "glitter",
    "neon", "neon lights", "light trail", "light streak",
    "motion blur", "slow motion", "time lapse", "hyperlapse",
    "animation", "motion graphics", "lower third", "title card",
    "transition", "wipe", "fade", "dissolve", "slide",
    "background loop", "seamless loop", "tileable",
    "green screen", "chroma key", "blue screen",
    "texture", "wallpaper", "pattern", "design",
    "wave", "waves", "ripple", "ripples", "flow",
    "smoke", "fire", "flame", "flames", "explosion",
    "water splash", "ink splash", "paint splash", "color splash",
    "bubble", "bubbles", "foam", "froth", "mist",
    "fog", "steam", "vapor", "haze", "dust",
    "rain", "raindrop", "raindrops", "snow", "snowflake",
    "lightning", "thunder", "storm", "hurricane", "tornado",
    "earthquake", "volcano", "eruption", "flood", "tsunami",
    # ── Generic success / achievement imagery ──
    "success", "successful", "succeed", "achievement", "achieve",
    "accomplish", "accomplishment", "complete", "completion",
    "win", "winner", "winning", "champion", "championship",
    "trophy", "medal", "gold", "silver", "bronze",
    "first place", "number one", "top", "best", "leading",
    "award", "award winning", "prize", "reward", "bonus",
    "recognition", "honor", "accolade", "praise", "applause",
    "standing ovation", "round of applause", "cheer", "cheering",
    "confetti", "balloon", "balloons", "firework", "fireworks",
    "celebrate", "celebration", "party", "festive", "festivity",
    "raise the bar", "set the bar", "new height", "new level",
    "next level", "take it to the next level", "level up",
    "game changer", "game changing", "paradigm shift",
    "breakthrough", "break through", "quantum leap",
    "leap forward", "giant leap", "big step", "milestone",
    "landmark", "turning point", "watershed moment",
    "tipping point", "critical mass", "momentum",
    "snowball effect", "domino effect", "ripple effect",
    "chain reaction", "catalyst", "spark", "trigger",
    "launch", "launchpad", "springboard", "stepping stone",
    "cornerstone", "foundation", "bedrock", "backbone",
    "pillar", "anchor", "keystone", "linchpin",
    "driving force", "moving force", "prime mover",
    "heart", "core", "essence", "soul", "spirit",
    "secret sauce", "magic ingredient", "special ingredient",
    "key ingredient", "essential element", "critical component",
    "winning formula", "success formula", "recipe for success",
    "road to success", "path to success", "journey to success",
    "ladder of success", "steps to success", "keys to success",
    "secrets of success", "habits of success", "success habits",
    "morning routine", "daily routine", "daily habits",
    "productive morning", "productive day", "productive routine",
    "power of habit", "power of routine", "power of discipline",
    "discipline", "self discipline", "willpower", "will power",
    "focus", "concentration", "attention", "mindfulness",
    "visualization", "mental imagery", "positive visualization",
    "affirmation", "positive affirmation", "daily affirmation",
    "gratitude", "thankful", "blessed", "grateful",
    "abundance mindset", "scarcity mindset", "poverty mindset",
    "rich mindset", "poor mindset", "money mindset",
    "financial freedom", "financial independence", "financial literacy",
    "passive income", "residual income", "multiple income streams",
    "side hustle", "side business", "moonlighting",
    "work from home", "remote work", "digital nomad",
    "location independent", "time freedom", "financial freedom",
    "early retirement", "retire early", "fire movement",
    "financial education", "money management", "personal finance",
    "budgeting", "saving money", "investing", "wealth building",
    "asset", "liability", "cash flow", "net worth",
    "real estate", "stock market", "index fund", "etf",
    "dividend", "compound interest", "passive investing",
    "active investing", "day trading", "swing trading",
    "forex", "crypto", "bitcoin", "ethereum", "nft",
    "defi", "web3", "blockchain", "distributed ledger",
    "smart contract", "dapp", "dao", "token", "tokenomics",
    "whale", "bull market", "bear market", "market cycle",
    "hype", "fomo", "fud", "bag holder", "moon",
    "to the moon", "hodl", "diamond hands", "paper hands",
    "rug pull", "pump and dump", "scam", "ponzi",
    "get rich quick", "get rich", "easy money", "fast money",
    "make money online", "earn money", "money making",
    "cash", "dollar", "dollar sign", "money bag",
    "money pile", "money stack", "money rain", "money shower",
    "gold coin", "gold bar", "gold ingot", "treasure",
    "vault", "safe", "lock", "key", "combination lock",
    "security camera", "surveillance", "monitoring",
    "alarm", "siren", "warning light", "caution tape",
    "do not enter", "restricted area", "authorized only",
    "confidential", "classified", "top secret", "secret file",
    "redacted", "blacked out", "censored", "blurred",
    "magnifying glass", "search", "investigation", "inspection",
    "audit", "review", "analysis", "assessment", "evaluation",
    "report", "document", "file", "folder", "binder",
    "spreadsheet", "database", "record", "log", "ledger",
    "receipt", "invoice", "bill", "statement", "balance",
    "check", "checkbook", "wallet", "purse", "coin purse",
    "credit card", "debit card", "atm", "bank teller",
    "bank vault", "safety deposit box", "lockbox",
    "loan", "mortgage", "credit", "debt", "interest rate",
    "apr", "annual percentage", "fixed rate", "variable rate",
    "amortization", "depreciation", "appreciation",
    "equity", "collateral", "down payment", "closing cost",
    "escrow", "title", "deed", "lien", "foreclosure",
    "bankruptcy", "insolvency", "liquidation", "restructuring",
    "merger", "acquisition", "takeover", "ipo",
    "valuation", "fundraising", "seed round", "series a",
    "venture capital", "angel investor", "private equity",
    "hedge fund", "mutual fund", "index", "benchmark",
    "bull", "bear", "stag", "market maker", "liquidity",
    "volatility", "correction", "crash", "rally", "recovery",
    "recession", "depression", "inflation", "deflation",
    "stagflation", "hyperinflation", "default", "bailout",
    "stimulus", "quantitative easing", "tightening",
    "interest", "dividend", "yield", "return", "gain",
    "loss", "expense", "cost", "overhead", "operating cost",
    "capital", "working capital", "cash reserve", "liquidity",
    "solvency", "profitability", "efficiency", "leverage",
    "goodwill", "intangible", "amortization", "depreciation",
    "accrual", "deferral", "prepaid", "outstanding",
    "receivable", "payable", "inventory", "supply chain",
    "logistics", "distribution", "wholesale", "retail",
    "ecommerce", "marketplace", "platform", "ecosystem",
    "funnel", "pipeline", "sales pipeline", "lead generation",
    "conversion", "acquisition", "retention", "churn",
    "lifetime value", "customer value", "unit economics",
    "cac", "ltv", "arpu", "mrr", "arr",
    "kpi", "metric", "dashboard", "analytics", "insights",
    "a/b test", "split test", "multivariate", "optimization",
    "personalization", "segmentation", "targeting",
    "campaign", "marketing campaign", "ad campaign",
    "social media", "content marketing", "influencer",
    "seo", "sem", "ppc", "cpm", "cpc", "ctr",
    "landing page", "sales page", "opt in", "lead magnet",
    "email list", "subscriber", "newsletter", "broadcast",
    "automation", "workflow", "drip campaign", "sequence",
    "webinar", "live stream", "podcast", "video series",
    "masterclass", "workshop", "training", "course",
    "coaching", "mentoring", "consulting", "advisory",
    "speaking", "keynote", "presentation", "talk",
    "book", "ebook", "guide", "handbook", "manual",
    "blueprint", "playbook", "roadmap", "checklist",
    "template", "worksheet", "workbook", "journal",
    "planner", "calendar", "schedule", "timeline",
    "system", "framework", "methodology", "approach",
    "strategy", "tactic", "technique", "tool", "resource",
    "hack", "life hack", "productivity hack", "time hack",
    "shortcut", "cheat sheet", "quick tip", "pro tip",
    "tip", "trick", "advice", "recommendation", "suggestion",
    "best practice", "industry standard", "gold standard",
    "benchmark", "baseline", "reference", "norm",
    "average", "typical", "standard", "common", "usual",
    "normal", "regular", "ordinary", "everyday", "routine",
    "basic", "fundamental", "essential", "necessary", "required",
    "important", "critical", "crucial", "vital", "key",
    "major", "significant", "substantial", "considerable",
    "massive", "huge", "enormous", "giant", "immense",
    "incredible", "unbelievable", "amazing", "astonishing",
    "astounding", "staggering", "stunning", "breathtaking",
    "mind blowing", "mind boggling", "jaw dropping",
    "eye opening", "thought provoking", "food for thought",
    "game changing", "revolutionary", "groundbreaking",
    "pioneering", "trailblazing", "cutting edge",
    "state of the art", "world class", "best in class",
    "top notch", "first rate", "a grade", "top tier",
    "premium", "deluxe", "luxury", "high end", "high quality",
    "quality", "excellence", "superior", "exceptional",
    "outstanding", "remarkable", "notable", "noteworthy",
    "impressive", "striking", "arresting", "captivating",
    "engaging", "compelling", "convincing", "persuasive",
    "powerful", "potent", "strong", "forceful", "dynamic",
    "energetic", "vibrant", "lively", "animated", "spirited",
    "enthusiastic", "passionate", "ardent", "fervent", "zealous",
    "dedicated", "committed", "devoted", "loyal", "faithful",
    "reliable", "dependable", "trustworthy", "responsible",
    "accountable", "answerable", "liable", "obligated",
    "professional", "competent", "capable", "able", "skilled",
    "talented", "gifted", "expert", "master", "specialist",
    "experienced", "seasoned", "veteran", "proficient",
    "knowledgeable", "informed", "educated", "trained",
    "qualified", "certified", "accredited", "licensed",
    "authorized", "approved", "sanctioned", "endorsed",
    "recommended", "suggested", "advised", "urged",
    "encouraged", "supported", "backed", "endorsed",
    "sponsored", "funded", "financed", "underwritten",
    "guaranteed", "warranted", "assured", "ensured",
    "protected", "covered", "insured", "secured",
    "safe", "secure", "protected", "guarded", "shielded",
    "defended", "fortified", "reinforced", "strengthened",
    "hardened", "toughened", "tempered", "seasoned",
    "tested", "proven", "validated", "verified", "confirmed",
    "established", "recognized", "acknowledged", "accepted",
    "approved", "authorized", "licensed", "registered",
    "certified", "accredited", "chartered", "qualified",
    "vetted", "screened", "background checked", "cleared",
    "bonded", "insured", "licensed", "registered",
    "compliant", "conforming", "adhering", "following",
    "meeting", "exceeding", "surpassing", "outperforming",
    "beating", "topping", "leading", "dominating",
    "controlling", "managing", "directing", "guiding",
    "leading", "steering", "navigating", "piloting",
    "captaining", "commanding", "heading", "running",
    "operating", "managing", "supervising", "overseeing",
    "monitoring", "tracking", "watching", "observing",
    "analyzing", "evaluating", "assessing", "reviewing",
    "auditing", "inspecting", "examining", "studying",
    "researching", "investigating", "probing", "exploring",
    "surveying", "polling", "questioning", "interviewing",
    "consulting", "advising", "counseling", "mentoring",
    "coaching", "training", "teaching", "instructing",
    "educating", "informing", "notifying", "alerting",
    "warning", "cautioning", "advising", "recommending",
    "suggesting", "proposing", "offering", "providing",
    "delivering", "supplying", "furnishing", "equipping",
    "outfitting", "gearing", "preparing", "readying",
    "setting", "arranging", "organizing", "coordinating",
    "planning", "scheduling", "timing", "budgeting",
    "forecasting", "projecting", "estimating", "calculating",
    "computing", "processing", "handling", "managing",
    "dealing", "coping", "handling", "addressing",
    "tackling", "confronting", "facing", "meeting",
    "encountering", "experiencing", "undergoing", "enduring",
    "surviving", "thriving", "flourishing", "prospering",
    "blooming", "blossoming", "flowering", "growing",
    "developing", "evolving", "maturing", "ripening",
    "aging", "seasoning", "curing", "fermenting",
    "brewing", "simmering", "cooking", "baking",
    "roasting", "grilling", "frying", "boiling",
    "steaming", "poaching", "braising", "stewing",
    "blending", "mixing", "combining", "merging",
    "fusing", "uniting", "joining", "connecting",
    "linking", "tying", "binding", "fastening",
    "attaching", "securing", "locking", "latching",
    "closing", "shutting", "sealing", "capping",
    "covering", "wrapping", "packaging", "boxing",
    "crating", "shipping", "transporting", "moving",
    "relocating", "transferring", "shifting", "switching",
    "changing", "altering", "modifying", "adjusting",
    "adapting", "transforming", "converting", "translating",
    "transcribing", "recording", "documenting", "capturing",
    "preserving", "conserving", "saving", "storing",
    "keeping", "maintaining", "sustaining", "supporting",
    "upholding", "defending", "protecting", "guarding",
    "safeguarding", "shielding", "screening", "filtering",
    "sorting", "classifying", "categorizing", "grouping",
    "clustering", "segmenting", "dividing", "splitting",
    "separating", "isolating", "insulating", "buffering",
    "cushioning", "padding", "lining", "layering",
    "stacking", "piling", "heaping", "mounting",
    "accumulating", "collecting", "gathering", "assembling",
    "building", "constructing", "creating", "making",
    "producing", "manufacturing", "fabricating", "assembling",
    "composing", "writing", "authoring", "drafting",
    "editing", "revising", "rewriting", "proofreading",
    "reviewing", "approving", "signing off", "clearing",
    "releasing", "publishing", "distributing", "disseminating",
    "broadcasting", "transmitting", "communicating",
    "conveying", "expressing", "articulating", "verbalizing",
    "stating", "declaring", "announcing", "proclaiming",
    "pronouncing", "asserting", "affirming", "confirming",
    "verifying", "validating", "authenticating", "certifying",
    "accrediting", "licensing", "registering", "chartering",
    "incorporating", "forming", "establishing", "founding",
    "launching", "starting", "beginning", "initiating",
    "commencing", "opening", "kicking off", "rolling out",
    "introducing", "unveiling", "revealing", "disclosing",
}

# ── INSURANCE CONTENT WHITELIST ───────────────────────────────────────────────
# When the content category is insurance, only these concrete concepts are allowed.
# This ensures b-roll visuals are directly tied to the spoken topic.
_INSURANCE_WHITELIST: set = {
    # Finance / money
    "finance", "financial", "money", "cash", "saving", "savings",
    "investment", "invest", "investing", "chart", "graph", "statistics",
    "bank", "banking", "account", "budget", "planning", "financial planning",
    # Risk / protection
    "risk", "protection", "safety", "security", "safe", "secure",
    "shield", "guard", "protect", "insurance", "coverage",
    # Policy / claims
    "policy", "claim", "claims", "document", "paperwork", "contract",
    "agreement", "signature", "signing", "application", "form",
    # Health / medical (for health insurance)
    "health", "medical", "hospital", "doctor", "clinic", "patient",
    "medicine", "prescription", "healthcare",
    # Home / car (for specific insurance types)
    "home", "house", "car", "vehicle", "family", "property",
    "accident", "road", "repair", "damage", "emergency",
    # Professional / office
    "office", "workspace", "desk", "laptop", "computer", "meeting",
    "consultation", "advisor", "agent", "broker", "customer service",
    "call center", "headset", "phone call",
}

# ── Layer 1: Heuristic scanner ────────────────────────────────────────────────

def _is_generic_concept(keyword: str) -> bool:
    """Check if a keyword is a generic/motivational concept that should be rejected."""
    kw_lower = keyword.lower().strip()
    if kw_lower in _GENERIC_CONCEPTS:
        return True
    # Also check if any word in the keyword is in the generic set
    for word in kw_lower.replace("-", " ").replace("_", " ").split():
        if word in _GENERIC_CONCEPTS:
            return True
    return False


def _is_insurance_relevant(keyword: str) -> bool:
    """Check if a keyword is relevant for insurance content."""
    kw_lower = keyword.lower().strip()
    if kw_lower in _INSURANCE_WHITELIST:
        return True
    # Check if any word in the keyword matches the whitelist
    for word in kw_lower.replace("-", " ").replace("_", " ").split():
        if word in _INSURANCE_WHITELIST:
            return True
    return False


def _scan_heuristic(words: List[Dict[str, Any]], duration: float, category: str = "unknown") -> SemanticEditPlan:
    """
    Instant keyword scan. No API call. Returns SemanticEditPlan from
    visual noun detection (B-roll) and impact word detection (SFX).
    """
    broll_cues: List[BrollCue] = []
    sfx_cues:   List[SfxCue]   = []

    for w in words:
        raw   = (w.get("word") or w.get("text") or "").strip()
        word  = raw.lower().rstrip(".,!?¿¡\"'")
        ts    = float(w.get("start", 0))

        if not word or ts < 0:
            continue

        # ── B-roll trigger ────────────────────────────────────────────────────
        kw: Optional[str] = None

        if _MONEY_RE.search(word) or _NUMBER_BIG.search(word):
            kw = "cash money"

        if kw is None:
            for lookup in _VISUAL_LOOKUPS:
                for fragment, search_term in lookup.items():
                    if fragment in word:
                        kw = search_term
                        break
                if kw:
                    break

        if kw and _BROLL_HOOK_GUARD <= ts <= duration - _BROLL_CTA_GUARD:
            # ── RULE 1: Reject cues shorter than 2.5s ──
            _dur = min(3.5, max(BROLL_MIN_OVERLAY_DURATION_S, duration - ts - 0.5))
            if _dur < BROLL_MIN_OVERLAY_DURATION_S:
                continue
            # ── RULE 2: Reject generic concepts ──
            if _is_generic_concept(kw):
                logger.debug("[SemanticPlanner/heuristic] Rejected generic concept: '%s'", kw)
                continue
            # ── RULE 3: Insurance content filter ──
            if category == "insurance" and not _is_insurance_relevant(kw):
                logger.debug("[SemanticPlanner/heuristic] Rejected non-insurance concept: '%s'", kw)
                continue
            if all(abs(ts - c.timestamp) >= _BROLL_MIN_GAP for c in broll_cues):
                if len(broll_cues) < _BROLL_MAX:
                    broll_cues.append(BrollCue(
                        timestamp=ts,
                        keyword=kw,
                        duration=_dur,
                        trigger_phrase=raw[:40],
                        confidence=0.70,
                    ))

        # ── SFX trigger ───────────────────────────────────────────────────────
        sfx_type: Optional[str]  = None
        sfx_int:  float           = 0.60

        if _MONEY_RE.search(word) or _NUMBER_BIG.search(word):
            sfx_type = "emphasis_word"
            sfx_int  = 0.90
        else:
            for trigger_set, stype, intensity in _SFX_TRIGGERS:
                if any(frag in word for frag in trigger_set):
                    sfx_type = stype
                    sfx_int  = intensity
                    break

        if sfx_type and ts > 0.5:
            if all(abs(ts - c.timestamp) >= _SFX_MIN_GAP for c in sfx_cues):
                if len(sfx_cues) < _SFX_MAX:
                    sfx_cues.append(SfxCue(
                        timestamp=ts,
                        sfx_type=sfx_type,
                        trigger_word=word[:30],
                        intensity=sfx_int,
                    ))

    return SemanticEditPlan(broll_cues=broll_cues, sfx_cues=sfx_cues, source="heuristic")


# ── Layer 2b: Frame extraction + Vision analysis ────────────────────────────

async def _extract_frames(
    clip_path: str,
    interval_s: float = _VISION_INTERVAL_S,
    max_frames: int = _VISION_MAX_FRAMES,
) -> List[Dict[str, Any]]:
    """
    Extract JPEG frames at *interval_s* intervals using FFmpeg.
    Returns [{t: float, b64: str}] list. Cleans up temp files automatically.
    """
    frames: List[Dict[str, Any]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="vcframes_") as tmpdir:
            out_pattern = os.path.join(tmpdir, "frame_%04d.jpg")
            cmd = [
                "ffmpeg", "-y", "-i", clip_path,
                "-vf", f"fps=1/{interval_s:.1f},scale=-1:360",
                "-q:v", "4",
                "-frames:v", str(max_frames),
                out_pattern,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                proc.kill()
                logger.debug("[FrameSampler] FFmpeg timeout")
                return frames

            for i, fp in enumerate(sorted(glob.glob(os.path.join(tmpdir, "frame_*.jpg")))):
                t = i * interval_s
                try:
                    with open(fp, "rb") as fh:
                        frames.append({"t": round(t, 2), "b64": base64.b64encode(fh.read()).decode()})
                except Exception:
                    pass
    except Exception as exc:
        logger.debug("[FrameSampler] failed: %s", exc)
    return frames


async def _analyze_frames_groq(
    frames: List[Dict[str, Any]],
) -> Optional[List[Dict[str, Any]]]:
    """
    Send all frames in a single Groq Vision request.
    Returns [{t, energy, expression, visual_interest, suggestion}] or None.
    """
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key or not frames:
        return None

    frame_index = "\n".join(f"  Frame {i}: t={f['t']:.0f}s" for i, f in enumerate(frames))
    text_prompt = (
        f"These are {len(frames)} sequential frames from a talking-head video clip.\n"
        f"Frame timestamps:\n{frame_index}\n\n"
        "For EACH frame return a JSON object with:\n"
        "- t: timestamp in seconds (match the frame index above)\n"
        "- energy: 0.0-1.0 (speaker animation/enthusiasm)\n"
        "- expression: 'neutral'|'excited'|'surprised'|'serious'|'smiling'\n"
        "- visual_interest: 'high'|'medium'|'low' (frame visual richness vs plain bg)\n"
        "- suggestion: 'zoom_punch'|'broll_needed'|'none'\n\n"
        "Return ONLY valid JSON: {\"frames\": [...]}"
    )

    content: List[Dict[str, Any]] = [{"type": "text", "text": text_prompt}]
    for frame in frames:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{frame['b64']}"},
        })

    try:
        async with httpx.AsyncClient(timeout=_VISION_TIMEOUT_S) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": _VISION_MODEL_GROQ,
                    "messages": [{"role": "user", "content": content}],
                    "max_tokens": 900,
                    "temperature": 0.10,
                    "response_format": {"type": "json_object"},
                },
            )
        if resp.status_code != 200:
            logger.debug("[VisionAnalyzer/Groq] HTTP %d: %s", resp.status_code, resp.text[:200])
            return None

        raw    = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, dict) and isinstance(parsed.get("frames"), list):
            return parsed["frames"]
        return None

    except Exception as exc:
        logger.debug("[VisionAnalyzer/Groq] failed: %s", exc)
        return None


async def _analyze_frames_ollama(
    frames: List[Dict[str, Any]],
) -> Optional[List[Dict[str, Any]]]:
    """
    Fallback: Ollama local vision model (Qwen-VL / LLaVA / MiniCPM-V).
    Processes frames one by one; returns None if Ollama unavailable.
    """
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{base_url}/api/tags")
            if r.status_code != 200:
                return None
            models = [m["name"] for m in r.json().get("models", [])]
            model  = next(
                (m for m in models
                 if any(n in m for n in ("qwen2.5vl", "qwen-vl", "llava", "minicpm"))),
                None,
            )
            if not model:
                return None
    except Exception:
        return None

    results: List[Dict[str, Any]] = []
    for frame in frames[:6]:   # cap at 6 for Ollama (slower per-frame)
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.post(
                    f"{base_url}/api/generate",
                    json={
                        "model":  model,
                        "prompt": (
                            f"Frame at t={frame['t']:.0f}s. Return JSON: "
                            '{"t":<s>,"energy":<0-1>,"expression":"neutral|excited|surprised|serious|smiling"'
                            ',"visual_interest":"high|medium|low","suggestion":"zoom_punch|broll_needed|none"}'
                        ),
                        "images": [frame["b64"]],
                        "format": "json",
                        "stream": False,
                    },
                )
                if r.status_code == 200:
                    data = r.json().get("response", "{}")
                    parsed = json.loads(data) if isinstance(data, str) else data
                    if isinstance(parsed, dict) and "energy" in parsed:
                        parsed.setdefault("t", frame["t"])
                        results.append(parsed)
        except Exception as exc:
            logger.debug("[VisionAnalyzer/Ollama] t=%s failed: %s", frame["t"], exc)
    return results or None


def _enhance_plan_with_vision(
    plan: SemanticEditPlan,
    vision_frames: List[Dict[str, Any]],
    duration: float,
    source_label: str = "vision_groq",
) -> SemanticEditPlan:
    """
    Enhance the heuristic/Groq plan with frame-level vision insights.

    - Adds ZoomCue for high-energy / expressive frames
    - Boosts B-roll confidence when frame visual interest is low
    - Reduces B-roll confidence when frame is already visually interesting
    """
    for frame in vision_frames:
        t      = float(frame.get("t", -1))
        energy = float(frame.get("energy", 0.0))
        expr   = str(frame.get("expression", "neutral")).lower()
        vis    = str(frame.get("visual_interest", "medium")).lower()
        sug    = str(frame.get("suggestion", "none")).lower()

        if t < 0 or t > duration:
            continue

        # ── Zoom cues from vision ─────────────────────────────────────────────
        is_expressive = expr in ("excited", "surprised")
        high_energy   = energy >= 0.72
        if (is_expressive or high_energy) and 1.0 < t < duration - 1.0:
            if all(abs(t - z.timestamp) >= _ZOOM_MIN_GAP for z in plan.zoom_cues):
                if len(plan.zoom_cues) < _ZOOM_MAX:
                    plan.zoom_cues.append(ZoomCue(
                        timestamp=t,
                        factor=round(min(1.15, 1.05 + energy * 0.11), 3),
                        duration=0.4,
                        reason=f"{expr}_expression" if is_expressive else "high_energy",
                        confidence=round(energy, 3),
                    ))

        # ── B-roll confidence adjustment ──────────────────────────────────────
        for cue in plan.broll_cues:
            if abs(cue.timestamp - t) <= 3.0:
                if vis == "low" or sug == "broll_needed":
                    cue.confidence = min(0.98, cue.confidence + 0.15)
                elif vis == "high":
                    cue.confidence = max(0.10, cue.confidence - 0.25)

    plan.zoom_cues = sorted(plan.zoom_cues, key=lambda z: z.timestamp)[:_ZOOM_MAX]
    plan.source    = source_label
    return plan


# ── Contextual SFX rules ─────────────────────────────────────────────────────

# Min gap between contextual SFX additions to avoid stacking
_CONTEXTUAL_SFX_GAP = 0.5


def _apply_contextual_sfx_rules(
    plan: SemanticEditPlan,
    words: List[Dict[str, Any]],
    duration: float,
) -> SemanticEditPlan:
    """
    Add contextual SFX cues based on the full edit plan + transcript.

    Rules (intelligent timing tied to visual events):
      R1  ZoomCue          → whoosh_zoom    @ zoom.t - 0.1s
      R2  BrollCue         → pop_broll      @ broll.t
      R3  insight/magic/cliff → riser_pre_reveal @ sfx.t - 2.2s
      R4  word boundary >0.90 prob, every ≥8s → camera_shutter @ word.end
      R5  cliffhanger      → bass_drop      @ sfx.t + 0.3s

    All rules respect the existing _CONTEXTUAL_SFX_GAP buffer to avoid stacking.
    """
    new_cues: List[SfxCue] = []

    def _can_place(t: float) -> bool:
        if t <= 0.05 or t >= duration - 0.1:
            return False
        return all(abs(t - c.timestamp) >= _CONTEXTUAL_SFX_GAP
                   for c in (plan.sfx_cues + new_cues))

    # R1 — Zoom punches get a directional whoosh
    for zoom in plan.zoom_cues:
        ts = max(0.05, zoom.timestamp - 0.10)
        if _can_place(ts):
            new_cues.append(SfxCue(
                timestamp=ts,
                sfx_type="whoosh_zoom",
                trigger_word="zoom_punch",
                intensity=0.75,
            ))

    # R2 — B-roll appearance gets a soft pop
    for broll in plan.broll_cues:
        if _can_place(broll.timestamp):
            new_cues.append(SfxCue(
                timestamp=broll.timestamp,
                sfx_type="pop_broll",
                trigger_word="broll_appear",
                intensity=0.50,
            ))

    # R3 — Tension riser 2.2s before any reveal/cliffhanger
    _RISER_TRIGGERS = {"insight_reveal", "magic_reveal", "cliffhanger"}
    for cue in list(plan.sfx_cues):
        if cue.sfx_type in _RISER_TRIGGERS:
            riser_t = cue.timestamp - 2.2
            if riser_t > 1.0 and _can_place(riser_t):
                new_cues.append(SfxCue(
                    timestamp=riser_t,
                    sfx_type="riser_pre_reveal",
                    trigger_word="pre_reveal",
                    intensity=0.60,
                ))

    # R4 — Camera shutter at narrative cuts (high-confidence word boundaries)
    _SHUTTER_INTERVAL = 8.0
    last_shutter = -_SHUTTER_INTERVAL
    high_prob_cuts = [
        float(w["end"]) for w in (words or [])
        if w.get("end") is not None
        and w.get("probability", 1.0) > 0.90
        and 3.0 < float(w["end"]) < duration - 2.0
    ]
    for cut_t in high_prob_cuts:
        if cut_t - last_shutter >= _SHUTTER_INTERVAL and _can_place(cut_t):
            new_cues.append(SfxCue(
                timestamp=cut_t,
                sfx_type="camera_shutter",
                trigger_word="jump_cut",
                intensity=0.35,
            ))
            last_shutter = cut_t

    # R5 — Bass drop 0.3s after cliffhanger word
    for cue in list(plan.sfx_cues):
        if cue.sfx_type == "cliffhanger":
            drop_t = cue.timestamp + 0.30
            if _can_place(drop_t):
                new_cues.append(SfxCue(
                    timestamp=drop_t,
                    sfx_type="bass_drop",
                    trigger_word="impact",
                    intensity=0.80,
                ))

    if new_cues:
        plan.sfx_cues.extend(new_cues)
        plan.sfx_cues.sort(key=lambda c: c.timestamp)
        logger.info(
            "[SemanticPlanner] contextual rules → +%d SFX (%s)",
            len(new_cues),
            ", ".join(f"{c.timestamp:.1f}s:{c.sfx_type}" for c in new_cues),
        )
    return plan


# ── Layer 2: Groq semantic batch pass ────────────────────────────────────────

def _build_windows(words: List[Dict[str, Any]], duration: float) -> List[Dict[str, Any]]:
    """Group word list into non-overlapping time windows of _WINDOW_S seconds."""
    windows: List[Dict[str, Any]] = []
    t = 0.0
    while t < duration:
        t_end = t + _WINDOW_S
        chunk = [w for w in words if t <= float(w.get("start", 0)) < t_end]
        if chunk:
            text = " ".join(
                (w.get("word") or w.get("text") or "") for w in chunk
            ).strip()
            windows.append({
                "t_start": round(t, 2),
                "t_end":   round(min(t_end, duration), 2),
                "text":    text,
                "words":   chunk,
            })
        t = t_end
    return windows


_GROQ_SYSTEM = (
    "You are a precise video editor. For each spoken text window decide:\n"
    "1. B-ROLL: Is there a visually concrete noun, action, place, or object? "
    "If yes, output a short English Pexels-style search keyword and the start timestamp.\n"
    "2. SFX: Is there a high-impact emotional word (revelation, big number, rhetorical "
    "question, transition)? If yes, output the SFX type and timestamp.\n\n"
    "Valid SFX types: insight_reveal | curiosity_gap | pattern_interrupt | "
    "cliffhanger | emphasis_word | transition\n\n"
    "Rules:\n"
    "- Only output broll/sfx when confidence >0.70\n"
    "- null means no cue for that category in that window\n"
    "- Each b-roll cue MUST have a minimum duration of 4 seconds.\n"
    "  Never generate a b-roll cue shorter than 4 seconds.\n"
    "  If the available window is less than 4 seconds, do not place b-roll there.\n"
    "- Return ONLY valid JSON: {\"results\": [{\"w\": <int>, "
    "\"broll\": {\"t\": <float>, \"kw\": \"<str>\"}|null, "
    "\"sfx\": {\"t\": <float>, \"type\": \"<str>\"}|null}]}"
)


async def _groq_semantic_pass(
    windows: List[Dict[str, Any]],
    duration: float,
) -> Optional[List[Dict[str, Any]]]:
    """
    Send all windows in a single Groq request.
    Returns list of per-window annotations or None on failure.
    """
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key or not windows:
        return None

    lines = [
        f"[{i}] T={win['t_start']:.1f}s–{win['t_end']:.1f}s: \"{win['text']}\""
        for i, win in enumerate(windows)
    ]
    user_msg = "\n".join(lines)

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {"role": "system", "content": _GROQ_SYSTEM},
                        {"role": "user",   "content": user_msg},
                    ],
                    "max_tokens": 700,
                    "temperature": 0.10,
                    "response_format": {"type": "json_object"},
                },
            )
        if resp.status_code != 200:
            logger.debug("[SemanticPlanner/Groq] HTTP %d", resp.status_code)
            return None

        raw = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(raw) if isinstance(raw, str) else raw

        # Unwrap envelope
        if isinstance(parsed, dict):
            for key in ("results", "data", "windows", "items"):
                if isinstance(parsed.get(key), list):
                    return parsed[key]
            return None
        if isinstance(parsed, list):
            return parsed
        return None

    except Exception as exc:
        logger.debug("[SemanticPlanner/Groq] failed: %s", exc)
        return None


def _merge_groq(
    plan: SemanticEditPlan,
    groq_results: List[Dict[str, Any]],
    windows: List[Dict[str, Any]],
    duration: float,
    category: str = "unknown",
) -> SemanticEditPlan:
    """Merge Groq annotations (confidence=0.90) on top of the heuristic plan."""
    for item in groq_results:
        win_idx = item.get("w", -1)
        win     = windows[win_idx] if 0 <= win_idx < len(windows) else {}
        context = win.get("text", "")[:50]

        # B-roll
        broll = item.get("broll")
        if isinstance(broll, dict):
            t  = float(broll.get("t", -1))
            kw = str(broll.get("kw", "")).strip()
            if kw and _BROLL_HOOK_GUARD <= t <= duration - _BROLL_CTA_GUARD:
                # ── RULE 1: Reject cues shorter than 2.5s ──
                _dur = min(3.5, max(BROLL_MIN_OVERLAY_DURATION_S, duration - t - 0.5))
                if _dur < BROLL_MIN_OVERLAY_DURATION_S:
                    logger.debug("[SemanticPlanner/groq] Skipped short b-roll cue at t=%.1fs (dur=%.1f < min=%.1f)", t, _dur, BROLL_MIN_OVERLAY_DURATION_S)
                    continue
                # ── RULE 2: Reject generic concepts ──
                if _is_generic_concept(kw):
                    logger.debug("[SemanticPlanner/groq] Rejected generic concept from LLM: '%s'", kw)
                    continue
                # ── RULE 3: Insurance content filter ──
                if category == "insurance" and not _is_insurance_relevant(kw):
                    logger.debug("[SemanticPlanner/groq] Rejected non-insurance concept from LLM: '%s'", kw)
                    continue
                if all(abs(t - c.timestamp) >= _BROLL_MIN_GAP for c in plan.broll_cues):
                    if len(plan.broll_cues) < _BROLL_MAX:
                        plan.broll_cues.append(BrollCue(
                            timestamp=t, keyword=kw,
                            duration=_dur,
                            trigger_phrase=context, confidence=0.90,
                        ))
                    else:
                        # Replace lowest-confidence heuristic entry
                        lo = min(range(len(plan.broll_cues)),
                                 key=lambda i: plan.broll_cues[i].confidence)
                        if plan.broll_cues[lo].confidence < 0.90:
                            plan.broll_cues[lo] = BrollCue(
                                timestamp=t, keyword=kw,
                                duration=_dur,
                                trigger_phrase=context, confidence=0.90,
                            )

        # SFX
        sfx = item.get("sfx")
        if isinstance(sfx, dict):
            t        = float(sfx.get("t", -1))
            sfx_type = str(sfx.get("type", "")).strip()
            if sfx_type in _VALID_SFX and t > 0.5:
                if all(abs(t - c.timestamp) >= _SFX_MIN_GAP for c in plan.sfx_cues):
                    if len(plan.sfx_cues) < _SFX_MAX:
                        plan.sfx_cues.append(SfxCue(
                            timestamp=t, sfx_type=sfx_type,
                            trigger_word=context[:25], intensity=0.85,
                        ))

    plan.broll_cues.sort(key=lambda c: c.timestamp)
    plan.sfx_cues.sort(key=lambda c: c.timestamp)
    plan.source = "groq"
    return plan


# ── Public entry point ────────────────────────────────────────────────────────

class SemanticEditPlanner:
    """
    Produces word-level B-roll and SFX cues from a word-timestamp transcript.

    plan = await SemanticEditPlanner().plan(words, duration, hook_type)
    plan.broll_cues  →  precise timestamps + search keywords for B-roll
    plan.sfx_cues    →  precise timestamps + SFX types
    """

    async def plan(
        self,
        words: List[Dict[str, Any]],
        duration: float,
        hook_type: str = "insight_reveal",
        category:  str = "unknown",
        clip_path: Optional[str] = None,
    ) -> SemanticEditPlan:
        """
        Build a SemanticEditPlan.

        Layer 1: Instant keyword heuristic (always, <10ms)
        Layer 2: Groq semantic text pass (~1.5s, when GROQ_API_KEY set)
        Layer 3: Frame vision analysis (~3-8s, when clip_path provided + GROQ_API_KEY set)

        Never raises — falls back gracefully at each layer.
        """
        if not words or duration <= 0:
            return SemanticEditPlan()

        try:
            # Layer 1: heuristic
            plan = _scan_heuristic(words, duration, category=category)
            logger.info(
                "[SemanticPlanner] heuristic → %d B-roll, %d SFX cues",
                len(plan.broll_cues), len(plan.sfx_cues),
            )

            # Guarantee at least one opening SFX cue from hook_type
            if hook_type in _VALID_SFX:
                has_early = any(c.timestamp < 1.5 for c in plan.sfx_cues)
                if not has_early:
                    plan.sfx_cues.insert(0, SfxCue(
                        timestamp=0.30,
                        sfx_type=hook_type,
                        trigger_word="hook_open",
                        intensity=0.90,
                    ))

            # Layer 2: Groq semantic text pass
            if os.environ.get("GROQ_API_KEY"):
                windows = _build_windows(words, duration)
                if windows:
                    groq_out = await _groq_semantic_pass(windows, duration)
                    if groq_out:
                        plan = _merge_groq(plan, groq_out, windows, duration, category=category)

            # Layer 3: Frame-level vision analysis
            # Runs when clip_path is available (post-render) and API key present.
            # Adds ZoomCues and refines B-roll confidence based on visual content.
            _vision_enabled = os.environ.get("VISION_ENABLED", "true").lower() != "false"
            if clip_path and os.path.isfile(clip_path) and _vision_enabled:
                try:
                    frames = await _extract_frames(clip_path)
                    if frames:
                        vision_data: Optional[List[Dict[str, Any]]] = None
                        source_lbl = "vision_groq"

                        if os.environ.get("GROQ_API_KEY"):
                            vision_data = await _analyze_frames_groq(frames)

                        if vision_data is None:
                            vision_data = await _analyze_frames_ollama(frames)
                            source_lbl  = "vision_ollama"

                        if vision_data:
                            plan = _enhance_plan_with_vision(plan, vision_data, duration, source_lbl)
                            logger.info(
                                "[SemanticPlanner] vision (%s) → +%d zoom cues, "
                                "B-roll confidence adjusted",
                                source_lbl, len(plan.zoom_cues),
                            )
                except Exception as _ve:
                    logger.debug("[SemanticPlanner] vision layer skipped: %s", _ve)

            # Layer 4: Contextual SFX rules — tie sound to visual events.
            # Adds whoosh@zoom, pop@broll, riser before reveal, shutter@cut,
            # bass_drop after cliffhanger. Pure logic, sub-millisecond.
            try:
                plan = _apply_contextual_sfx_rules(plan, words, duration)
            except Exception as _re:
                logger.debug("[SemanticPlanner] contextual SFX rules skipped: %s", _re)

            # ── Validation: enforce minimum 4s B-roll duration ────────────────
            # LLM may return short cues despite prompt instructions.
            # Extend short cues to 4s, or remove if they exceed clip duration.
            # ── RULE 6: Filter out generic/fallback concepts from final cues ──
            # ── RULE 7: Skip cues that cannot be made relevant and long enough ─
            _MIN_BROLL_DUR = MIN_OVERLAY_DURATION_S
            _valid_broll = []
            for cue in plan.broll_cues:
                # RULE 6: Reject generic/fallback concepts even in final validation
                if _is_generic_concept(cue.keyword):
                    logger.info(
                        "[SemanticPlanner] RULE 6: Removing generic fallback concept '%s' at t=%.1fs",
                        cue.keyword, cue.timestamp,
                    )
                    continue
                # RULE 7: If extending to minimum duration would exceed clip, skip
                if cue.timestamp + max(cue.duration, _MIN_BROLL_DUR) > duration:
                    logger.info(
                        "[SemanticPlanner] RULE 7: Skipping b-roll cue at t=%.1fs "
                        "(dur=%.1fs cannot be extended to min=%.1fs without exceeding clip %.1fs)",
                        cue.timestamp, cue.duration, _MIN_BROLL_DUR, duration,
                    )
                    continue
                if cue.duration < _MIN_BROLL_DUR:
                    cue.duration = _MIN_BROLL_DUR
                if cue.timestamp + cue.duration > duration:
                    logger.info(
                        "[SemanticPlanner] Removing b-roll cue at t=%.1fs (dur=%.1fs exceeds clip %.1fs)",
                        cue.timestamp, cue.duration, duration,
                    )
                    continue
                _valid_broll.append(cue)
            if len(_valid_broll) < len(plan.broll_cues):
                logger.info(
                    "[SemanticPlanner] B-roll validation: %d → %d cues (min_dur=%.1fs)",
                    len(plan.broll_cues), len(_valid_broll), _MIN_BROLL_DUR,
                )
            plan.broll_cues = _valid_broll

            # Final caps + sort
            plan.broll_cues = sorted(plan.broll_cues, key=lambda c: c.timestamp)[:_BROLL_MAX]
            plan.sfx_cues   = sorted(plan.sfx_cues,   key=lambda c: c.timestamp)[:_SFX_MAX]
            plan.zoom_cues  = sorted(plan.zoom_cues,  key=lambda z: z.timestamp)[:_ZOOM_MAX]

            logger.info(
                "[SemanticPlanner] final (source=%s): B-roll=[%s] SFX=[%s] Zoom=[%s]",
                plan.source,
                ", ".join(f"{c.timestamp:.1f}s:{c.keyword}" for c in plan.broll_cues) or "—",
                ", ".join(f"{c.timestamp:.1f}s:{c.sfx_type}" for c in plan.sfx_cues) or "—",
                ", ".join(f"{z.timestamp:.1f}s:{z.factor}x" for z in plan.zoom_cues) or "—",
            )
            return plan

        except Exception as exc:
            logger.warning("[SemanticPlanner] plan() failed: %s", exc)
            return SemanticEditPlan()
