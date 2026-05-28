"""
Enhanced B-roll Service with Visual Context Analysis
Analyzes content context to suggest and insert relevant B-roll footage.
"""

import logging
import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
from enum import Enum
import asyncio

logger = logging.getLogger(__name__)


class VisualContextType(Enum):
    """Types of visual contexts that can be detected."""
    TUTORIAL_DEMO = "tutorial_demo"      # Screen recording, hands-on
    PERSON_TALKING = "person_talking"  # Talking head
    PRODUCT_SHOWCASE = "product_showcase"  # Product features
    LOCATION_SCENES = "location_scenes"  # Outdoor/location shots
    SCREEN_RECORDING = "screen_recording"  # Digital interface
    EMOTIONAL_MOMENT = "emotional_moment"  # Emotional reactions
    ACTION_SEQUENCE = "action_sequence"  # Dynamic movement
    TEXT_HEAVY = "text_heavy"           # Text overlays, infographics


@dataclass
class BrollOpportunity:
    """Identified opportunity for B-roll insertion."""
    timestamp: float
    duration: float
    context_type: VisualContextType
    description: str
    confidence: float
    suggested_keywords: List[str]
    visual_gap_score: float  # How much visual support is needed (0-100)


@dataclass
class BrollClip:
    """B-roll clip suggestion."""
    source: str  # 'stock', 'generated', 'suggested_search'
    keywords: List[str]
    duration: float
    preview_url: Optional[str]
    relevance_score: float
    context_match: VisualContextType
    insertion_point: float


class EnhancedBrollService:
    """
    Enhanced B-roll service with visual context analysis.
    """
    
    # Context detection patterns (EN + ES for insurance/finance beta)
    CONTEXT_PATTERNS = {
        VisualContextType.TUTORIAL_DEMO: [
            r"click (on|this)", r"open (the|settings)", r"drag (and drop|this)",
            r"type (this|in)", r"select (the|option)", r"press (button|key)",
            r"enter (data|text)", r"upload (file|image)", r"download (the|file)",
            # Spanish
            r"haz clic", r"abre (la|el)", r"selecciona", r"presiona",
            r"ingresa (los|la)", r"sube (el|la)", r"descarga"
        ],
        VisualContextType.PRODUCT_SHOWCASE: [
            r"this product", r"feature (is|allows)", r"comes with",
            r"includes", r"design (is|features)", r"quality (materials|build)",
            r"look at this", r"check this out", r"here's the",
            # Spanish — insurance/finance
            r"este (producto|seguro|plan)", r"esta (póliza|cobertura)",
            r"incluye", r"cubre", r"protege", r"beneficio",
            r"te (ofrecemos|damos|garantizamos)",
            r"nuestro (seguro|plan|producto)"
        ],
        VisualContextType.LOCATION_SCENES: [
            r"we're at", r"this place", r"location", r"scenery",
            r"landscape", r"beautiful view", r"over here", r"in this (city|area|country)",
            # Spanish
            r"estamos en", r"este (lugar|sitio|país|barrio)",
            r"aquí (en|está)", r"en esta (zona|ciudad|región)",
            r"oficina", r"edificio", r"sucursal"
        ],
        VisualContextType.SCREEN_RECORDING: [
            r"screen", r"interface", r"dashboard", r"app", r"website",
            r"software", r"program", r"platform", r"tool",
            # Spanish
            r"pantalla", r"interfaz", r"aplicación", r"app",
            r"plataforma", r"portal", r"panel", r"dashboard"
        ],
        VisualContextType.EMOTIONAL_MOMENT: [
            r"amazing", r"incredible", r"shocking", r"emotional",
            r"touching", r"heartwarming", r"surprising", r"unbelievable",
            r"can't believe", r"so (happy|sad|excited|angry)",
            # Spanish
            r"increíble", r"impresionante", r"sorprendente",
            r"tranquilidad", r"confianza", r"seguridad",
            r"protección", r"paz mental", r"tranquilo",
            r"no te preocupes", r"estás (cubierto|protegido)"
        ],
        VisualContextType.ACTION_SEQUENCE: [
            r"watch me", r"look at this", r"doing this", r"demonstrating",
            r"showing you", r"here's how", r"let me (show|demonstrate)",
            # Spanish
            r"mira (esto|cómo)", r"te muestro", r"vamos a (ver|hacer)",
            r"así es como", r"déjame (mostrarte|explicarte)"
        ],
        VisualContextType.TEXT_HEAVY: [
            r"statistics", r"numbers", r"data shows", r"according to",
            r"research", r"study", r"percent", r"graph", r"chart",
            # Spanish — insurance/finance
            r"estadísticas", r"números", r"datos (muestran|indican)",
            r"según", r"estudio", r"investigación",
            r"porcentaje", r"por ciento", r"gráfica", r"tabla",
            r"promedio", r"cifras", r"resultados",
            r"prima", r"deducible", r"cobertura", r"límite"
        ]
    }
    
    # B-roll sources by context
    BROLL_SOURCES = {
        VisualContextType.TUTORIAL_DEMO: {
            "primary": ["screen recording", "demo footage", "UI capture"],
            "fallback": ["hands typing", "computer screens", "tech interface"]
        },
        VisualContextType.PRODUCT_SHOWCASE: {
            "primary": ["product photography", "detail shots", "360 view"],
            "fallback": ["hands holding product", "unboxing", "lifestyle shot"]
        },
        VisualContextType.LOCATION_SCENES: {
            "primary": ["establishing shot", "b-roll location", "scenic view"],
            "fallback": ["drone footage", "pan shot", "wide angle"]
        },
        VisualContextType.SCREEN_RECORDING: {
            "primary": ["screen capture", "software demo", "UI walkthrough"],
            "fallback": ["monitor display", "digital interface", "tech closeup"]
        },
        VisualContextType.EMOTIONAL_MOMENT: {
            "primary": ["reaction shot", "closeup face", "emotional b-roll"],
            "fallback": ["hands gesture", "eye contact", "expression"]
        },
        VisualContextType.ACTION_SEQUENCE: {
            "primary": ["action shot", "movement b-roll", "dynamic footage"],
            "fallback": ["slow motion", "detail shot", "process footage"]
        },
        VisualContextType.TEXT_HEAVY: {
            "primary": ["infographic", "data visualization", "chart animation"],
            "fallback": ["text overlay", "graphic element", "visual data"]
        },
        VisualContextType.PERSON_TALKING: {
            "primary": ["talking head", "interview setup", "speaker footage"],
            "fallback": ["listening shot", "audience reaction", "context shot"]
        }
    }
    
    def __init__(self):
        self.ai_service = None  # Lazy loaded
    
    async def analyze_transcript_for_broll(
        self,
        transcript: str,
        word_timings: List[Dict[str, Any]]
    ) -> List[BrollOpportunity]:
        """
        Analyze transcript to find B-roll opportunities.
        """
        opportunities = []
        
        # Split into segments based on timing
        segments = self._segment_transcript(transcript, word_timings)
        
        for segment in segments:
            text = segment["text"].lower()
            
            # Detect visual context
            context_scores = self._detect_visual_context(text)
            
            if not context_scores:
                continue
            
            # Get best matching context
            best_context = max(context_scores.items(), key=lambda x: x[1])
            context_type, confidence = best_context
            
            # Calculate visual gap score (how much B-roll is needed)
            visual_gap = self._calculate_visual_gap(text, context_type)
            
            # Generate keywords for B-roll search
            keywords = self._generate_broll_keywords(text, context_type)
            
            opportunity = BrollOpportunity(
                timestamp=segment["start"],
                duration=segment["end"] - segment["start"],
                context_type=context_type,
                description=self._generate_description(text, context_type),
                confidence=confidence,
                suggested_keywords=keywords,
                visual_gap_score=visual_gap
            )
            
            # Only add high-confidence opportunities with real visual needs
            if confidence > 0.6 and visual_gap > 50:
                opportunities.append(opportunity)
        
        # Sort by visual gap score (highest need first)
        opportunities.sort(key=lambda x: x.visual_gap_score, reverse=True)
        
        return opportunities
    
    def _segment_transcript(
        self,
        transcript: str,
        word_timings: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Segment transcript into logical chunks for analysis."""
        if not word_timings:
            # Fallback: segment by sentences
            sentences = re.split(r'[.!?]+', transcript)
            segments = []
            current_time = 0
            for sentence in sentences:
                if sentence.strip():
                    duration = len(sentence.split()) * 0.5  # Estimate
                    segments.append({
                        "text": sentence.strip(),
                        "start": current_time,
                        "end": current_time + duration,
                        "words": sentence.split()
                    })
                    current_time += duration
            return segments
        
        # Group words into segments (3-7 seconds each)
        segments = []
        current_words = []
        segment_start = word_timings[0]["start"] if word_timings else 0
        
        for word in word_timings:
            current_words.append(word)
            
            # Create segment when we have enough words or time gap
            if len(current_words) >= 5 or (word["end"] - segment_start) > 4:
                segments.append({
                    "text": " ".join(w["text"] for w in current_words),
                    "start": segment_start,
                    "end": word["end"],
                    "words": current_words
                })
                current_words = []
                segment_start = word.get("start", word.get("end", segment_start + 0.5))
        
        # Add remaining words
        if current_words:
            segments.append({
                "text": " ".join(w["text"] for w in current_words),
                "start": segment_start,
                "end": current_words[-1].get("end", segment_start + 2),
                "words": current_words
            })
        
        return segments
    
    def _detect_visual_context(self, text: str) -> Dict[VisualContextType, float]:
        """Detect visual context types in text."""
        scores = {}
        
        for context_type, patterns in self.CONTEXT_PATTERNS.items():
            matches = sum(1 for pattern in patterns if re.search(pattern, text, re.IGNORECASE))
            if matches > 0:
                # Calculate confidence based on matches
                confidence = min(1.0, 0.3 + (matches * 0.2))
                scores[context_type] = confidence
        
        return scores
    
    def _calculate_visual_gap(self, text: str, context: VisualContextType) -> float:
        """
        Calculate how much visual support is needed.
        High score = needs lots of B-roll
        """
        score = 50  # Base score
        
        # Boost score for certain contexts
        context_boosts = {
            VisualContextType.TUTORIAL_DEMO: 30,
            VisualContextType.PRODUCT_SHOWCASE: 25,
            VisualContextType.EMOTIONAL_MOMENT: 20,
        }
        
        score += context_boosts.get(context, 10)
        
        # Long text without visual references = higher gap
        words = len(text.split())
        if words > 20:
            score += min(20, (words - 20) * 0.5)
        
        # Technical jargon = higher gap
        technical_terms = len(re.findall(r'\b(configure|implement|integrate|optimize|algorithm|API|database)\b', text, re.IGNORECASE))
        score += technical_terms * 5
        
        return min(100, score)
    
    def _generate_broll_keywords(
        self,
        text: str,
        context: VisualContextType
    ) -> List[str]:
        """Generate search keywords for B-roll footage."""
        # Get base keywords from context
        sources = self.BROLL_SOURCES.get(context, {})
        keywords = sources.get("primary", [])
        
        # Extract specific nouns from text
        # Simple approach: extract capitalized words and technical terms
        specific_terms = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
        
        # Clean and combine
        result = list(keywords)
        for term in specific_terms[:3]:  # Top 3 specific terms
            clean_term = term.lower()
            if len(clean_term) > 3:
                result.append(f"{clean_term} {keywords[0] if keywords else 'footage'}")
        
        return result[:6]  # Limit to 6 keywords
    
    def _generate_description(self, text: str, context: VisualContextType) -> str:
        """Generate a description of the B-roll needed."""
        descriptions = {
            VisualContextType.TUTORIAL_DEMO: f"Screen recording or demo footage showing: '{text[:50]}...'",
            VisualContextType.PRODUCT_SHOWCASE: f"Product shots and closeups for: '{text[:50]}...'",
            VisualContextType.LOCATION_SCENES: f"Establishing shots and B-roll of location mentioned in: '{text[:50]}...'",
            VisualContextType.SCREEN_RECORDING: f"Screen capture footage for interface demonstration: '{text[:50]}...'",
            VisualContextType.EMOTIONAL_MOMENT: f"Reaction shots and emotional B-roll to emphasize: '{text[:50]}...'",
            VisualContextType.ACTION_SEQUENCE: f"Action shots and movement footage for: '{text[:50]}...'",
            VisualContextType.TEXT_HEAVY: f"Infographics, charts, or text overlays for data: '{text[:50]}...'",
            VisualContextType.PERSON_TALKING: f"Cutaway shots and context B-roll while speaker discusses: '{text[:50]}...'",
        }
        
        return descriptions.get(context, f"B-roll footage for: '{text[:50]}...'")
    
    async def find_broll_footage(
        self,
        opportunity: BrollOpportunity,
        video_path: Optional[Path] = None
    ) -> List[BrollClip]:
        """
        Find or suggest B-roll footage for an opportunity.
        """
        clips = []
        
        # Generate from keywords
        for keyword in opportunity.suggested_keywords[:3]:
            clip = BrollClip(
                source="suggested_search",
                keywords=keyword.split(),
                duration=opportunity.duration,
                preview_url=None,
                relevance_score=opportunity.confidence * 0.8,
                context_match=opportunity.context_type,
                insertion_point=opportunity.timestamp
            )
            clips.append(clip)
        
        # If we have video path, look for matching footage within it
        if video_path and video_path.exists():
            internal_clips = await self._find_internal_broll(video_path, opportunity)
            clips.extend(internal_clips)
        
        # Sort by relevance
        clips.sort(key=lambda x: x.relevance_score, reverse=True)
        
        return clips[:3]  # Return top 3 options
    
    async def _find_internal_broll(
        self,
        video_path: Path,
        opportunity: BrollOpportunity
    ) -> List[BrollClip]:
        """Find relevant footage within the same video."""
        # This would use scene detection to find relevant alternative shots
        # For now, return placeholder
        return []
    
    async def generate_broll_suggestions(
        self,
        transcript: str,
        video_path: Optional[Path] = None,
        word_timings: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Main entry point: Generate comprehensive B-roll suggestions.
        """
        # Analyze transcript
        opportunities = await self.analyze_transcript_for_broll(
            transcript,
            word_timings or []
        )
        
        # Find footage for each opportunity
        suggestions = []
        for opp in opportunities[:5]:  # Top 5 opportunities
            clips = await self.find_broll_footage(opp, video_path)
            if clips:
                suggestions.append({
                    "opportunity": {
                        "timestamp": opp.timestamp,
                        "duration": opp.duration,
                        "context": opp.context_type.value,
                        "confidence": opp.confidence,
                        "visual_gap_score": opp.visual_gap_score,
                        "description": opp.description
                    },
                    "suggested_clips": [
                        {
                            "source": clip.source,
                            "keywords": clip.keywords,
                            "duration": clip.duration,
                            "relevance_score": clip.relevance_score,
                            "insertion_point": clip.insertion_point
                        }
                        for clip in clips
                    ]
                })
        
        return {
            "total_opportunities": len(opportunities),
            "high_priority_suggestions": suggestions,
            "summary": self._generate_summary(suggestions)
        }
    
    def _generate_summary(self, suggestions: List[Dict[str, Any]]) -> str:
        """Generate a human-readable summary of B-roll needs."""
        if not suggestions:
            return "No significant B-roll opportunities detected. Content appears to have sufficient visual support."
        
        contexts = [s["opportunity"]["context"] for s in suggestions]
        context_counts = {}
        for c in contexts:
            context_counts[c] = context_counts.get(c, 0) + 1
        
        summary_parts = [
            f"Found {len(suggestions)} high-priority B-roll opportunities."
        ]
        
        for context, count in sorted(context_counts.items(), key=lambda x: x[1], reverse=True):
            summary_parts.append(f"- {count} opportunities for {context.replace('_', ' ')} footage")
        
        return " ".join(summary_parts)


# Global instance
_broll_service: Optional[EnhancedBrollService] = None


def get_enhanced_broll_service() -> EnhancedBrollService:
    """Get global enhanced B-roll service instance."""
    global _broll_service
    if _broll_service is None:
        _broll_service = EnhancedBrollService()
    return _broll_service


async def analyze_broll_needs(
    transcript: str,
    video_path: Optional[Path] = None,
    word_timings: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Convenience function to analyze B-roll needs.
    
    Returns comprehensive B-roll suggestions with visual context analysis.
    """
    service = get_enhanced_broll_service()
    return await service.generate_broll_suggestions(transcript, video_path, word_timings)
