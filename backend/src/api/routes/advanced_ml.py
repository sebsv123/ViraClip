"""
Advanced ML API Routes — Phase 8 Quantum & Evolution
======================================================

Endpoints for quantum-inspired virality simulation and
swarm evolution viral engine.

Router prefix: /api/ml
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, ConfigDict, Field

from ...services.quantum_virality_simulator import QuantumViralitySimulator, simulate_viral_variants
from ...services.swarm_evolution_engine import SwarmEvolutionEngine, evolve_clip_genome

router = APIRouter(prefix="/ml", tags=["Advanced ML"])


# ============ Quantum-Inspired Simulator ============

class QuantumSimRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "clip_text": "You won't believe what happens when you mix these two ingredients!",
                "duration": 45.0,
                "platform": "tiktok",
                "num_universes": 100,
            }
        }
    )

    clip_text: str = Field(..., min_length=10, max_length=2000)
    duration: float = Field(60.0, ge=15, le=300)
    platform: str = Field("tiktok")
    num_universes: int = Field(100, ge=20, le=500)


@router.post("/quantum-simulate")
async def quantum_simulate(request: QuantumSimRequest) -> Dict[str, Any]:
    """
    Quantum-Inspired Virality Simulator (Phase 8.1).
    
    Simulates 100+ parallel viral universes with different hook configurations,
    calculates interference patterns, and returns top-3 variants.
    
    Key innovations:
    - 100+ parallel universe simulation
    - "Interference" effects between feature combinations
    - 70% compute savings vs rendering all variants
    - Diversity score via Shannon entropy
    """
    simulator = QuantumViralitySimulator()
    
    clip_features = {
        "text": request.clip_text,
        "duration": request.duration,
    }
    
    try:
        result = await simulator.simulate_parallel_universes(
            clip_features,
            num_universes=request.num_universes,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quantum-simulate/demo")
async def quantum_simulate_demo() -> Dict[str, Any]:
    """Demo endpoint with sample clip features."""
    demo_features = {
        "text": "This shocking discovery will change how you think about productivity forever! Scientists were amazed.",
        "duration": 52.0,
    }
    
    result = await simulate_viral_variants(demo_features, num_variants=50)
    result["demo"] = True
    result["note"] = "This is a demo with 50 simulated universes. Use POST /quantum-simulate for custom input."
    return result


# ============ Swarm Evolution Engine ============

class EvolutionRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "clip_text": "3 tips that will revolutionize your morning routine",
                "duration": 58.0,
                "content_type": "educational",
                "population_size": 50,
                "generations": 10,
            }
        }
    )

    clip_text: str = Field(..., min_length=10, max_length=2000)
    duration: float = Field(60.0, ge=15, le=300)
    content_type: str = Field("entertainment")
    population_size: int = Field(50, ge=20, le=100)
    generations: int = Field(10, ge=5, le=20)


@router.post("/evolve")
async def evolve_clip(request: EvolutionRequest) -> Dict[str, Any]:
    """
    Swarm Evolution Viral Engine (Phase 8.2).
    
    Uses genetic algorithms to evolve clip variants through selection,
    crossover, and mutation. Population evolves over generations to
    find optimal gene combinations.
    
    Features:
    - 50 individuals per population
    - 10 generations of evolution
    - Elite preservation (top 5 survive)
    - Fitness progression visualization
    - Content-type aware optimization
    """
    engine = SwarmEvolutionEngine()
    
    clip_features = {
        "text": request.clip_text,
        "duration": request.duration,
    }
    
    try:
        result = await engine.evolve_viral_clip(
            clip_features,
            population_size=request.population_size,
            generations=request.generations,
            content_type=request.content_type,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/evolve/demo")
async def evolve_demo() -> Dict[str, Any]:
    """Demo evolution with sample clip."""
    demo_features = {
        "text": "The secret to viral content that no one talks about. This changes everything!",
        "duration": 47.0,
    }
    
    result = await evolve_clip_genome(
        demo_features,
        population_size=30,
        generations=8,
        content_type="entertainment",
    )
    result["demo"] = True
    result["note"] = "This is a demo with 30 individuals over 8 generations. Use POST /evolve for custom input."
    return result


# ============ Combined Analysis ============

@router.post("/analyze")
async def combined_ml_analysis(
    clip_text: str,
    duration: float = 60.0,
    content_type: str = "entertainment",
) -> Dict[str, Any]:
    """
    Run both quantum simulation and swarm evolution, return combined analysis.
    
    Provides comprehensive AI-powered optimization recommendations.
    """
    clip_features = {
        "text": clip_text,
        "duration": duration,
    }
    
    # Run both simulations in parallel
    quantum_task = simulate_viral_variants(clip_features, num_variants=50)
    evolution_task = evolve_clip_genome(
        clip_features,
        population_size=30,
        generations=8,
        content_type=content_type,
    )
    
    quantum_result, evolution_result = await asyncio.gather(quantum_task, evolution_task)
    
    # Combine insights
    return {
        "quantum_simulation": quantum_result,
        "evolution_engine": evolution_result,
        "combined_recommendations": _combine_recommendations(quantum_result, evolution_result),
        "optimal_strategy": _determine_optimal_strategy(quantum_result, evolution_result),
    }


def _combine_recommendations(quantum: Dict, evolution: Dict) -> List[str]:
    """Combine recommendations from both methods."""
    recs = []
    
    # From quantum simulation
    top_quantum = quantum.get("top_variants", [{}])[0]
    recs.extend(top_quantum.get("recommendations", [])[:2])
    
    # From evolution
    top_evolution = evolution.get("top_survivors", [{}])[0]
    recs.extend(top_evolution.get("implementation_guide", [])[:2])
    
    # Combined insight
    diversity_q = quantum.get("diversity_score", 0)
    improvement_e = evolution.get("summary", {}).get("fitness_improvement", 0)
    
    if diversity_q > 0.7 and improvement_e > 20:
        recs.append("High consensus between quantum and evolutionary models — recommendations have high confidence")
    
    return recs


def _determine_optimal_strategy(quantum: Dict, evolution: Dict) -> Dict[str, Any]:
    """Determine optimal strategy combining both approaches."""
    
    # Get top results
    q_variant = quantum.get("top_variants", [{}])[0]
    e_variant = evolution.get("top_survivors", [{}])[0]
    
    q_confidence = q_variant.get("confidence", 0)
    e_fitness = e_variant.get("fitness", 0)
    
    # Weighted combination
    if q_confidence > 0.7 and e_fitness > 0.7:
        strategy = "aggressive_viral"
        confidence = "high"
    elif q_confidence > 0.6 or e_fitness > 0.6:
        strategy = "balanced_viral"
        confidence = "medium"
    else:
        strategy = "conservative"
        confidence = "low"
    
    return {
        "strategy": strategy,
        "confidence": confidence,
        "expected_virality": round((q_confidence + e_fitness) / 2, 3),
        "primary_hook_timing": q_variant.get("hook_config", {}).get("hook_timing", 1.0),
        "recommended_cut_speed": e_variant.get("genome", {}).get("genes", {}).get("cut_speed", "medium"),
    }


import asyncio

__all__ = ["router"]
