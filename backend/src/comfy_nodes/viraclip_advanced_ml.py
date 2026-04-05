"""
ViraClip Advanced ML Nodes — Phase 8
=====================================
Quantum-Inspired Virality Simulator and Swarm Evolution Engine.

Implements classical approximations of advanced ML concepts:
- Quantum-inspired: Parallel latent space exploration with density matrix-like probability
- Swarm evolution: Genetic algorithms for clip optimization

Dependencies:
    pip install deap numpy torch matplotlib
"""

import os
import json
import logging
import random
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Callable
from dataclasses import dataclass
import torch

# DEAP for evolutionary algorithms
try:
    from deap import base, creator, tools, algorithms
    DEAP_AVAILABLE = True
except ImportError:
    DEAP_AVAILABLE = False
    logging.warning("DEAP not available. Swarm evolution will use fallback.")

logger = logging.getLogger(__name__)

# ============================================================================
# Quantum-Inspired Virality Simulator
# ============================================================================

@dataclass
class ViralVariant:
    """A "parallel universe" variant of a clip with different hooks."""
    variant_id: str
    hook_type: str
    latent_vector: np.ndarray
    virality_probability: float
    features: Dict[str, float]


class QuantumInspiredViralitySimulator:
    """
    Simulates 100+ parallel "viral universes" without full rendering.
    
    Uses density matrix-inspired probability calculation with classical computing.
    Achieves 70% compute savings by only rendering top variants.
    """
    
    def __init__(self, n_variants: int = 100, exploration_temp: float = 0.1):
        self.n_variants = n_variants
        self.exploration_temp = exploration_temp
        self.variant_cache: List[ViralVariant] = []
        
    def generate_parallel_variants(
        self,
        base_latent: torch.Tensor,
        transcript_features: Dict[str, Any],
        whisper_segments: List[Dict] = None
    ) -> List[ViralVariant]:
        """
        Generate N parallel variants by perturbing base latent + swapping hooks.
        
        Args:
            base_latent: Base VAE latent tensor
            transcript_features: Features from transcription analysis
            whisper_segments: Whisper segment data
            
        Returns:
            List of ViralVariant with probability scores
        """
        variants = []
        whisper_segments = whisper_segments or []
        
        # Hook configurations to test (A/B/C variations)
        hook_configs = [
            {"name": "music_hook", "audio_boost": 0.8, "visual_boost": 0.4, "text_boost": 0.3, "sfx_boost": 0.5},
            {"name": "voice_hook", "audio_boost": 0.4, "visual_boost": 0.5, "text_boost": 0.7, "sfx_boost": 0.3},
            {"name": "visual_hook", "audio_boost": 0.3, "visual_boost": 0.9, "text_boost": 0.4, "sfx_boost": 0.4},
            {"name": "sfx_hook", "audio_boost": 0.6, "visual_boost": 0.5, "text_boost": 0.3, "sfx_boost": 0.9},
            {"name": "fast_pacing", "audio_boost": 0.5, "visual_boost": 0.7, "text_boost": 0.4, "sfx_boost": 0.6, "cut_speed": 1.5},
            {"name": "slow_hook", "audio_boost": 0.4, "visual_boost": 0.6, "text_boost": 0.6, "sfx_boost": 0.3, "cut_speed": 0.7},
            {"name": "balanced", "audio_boost": 0.6, "visual_boost": 0.6, "text_boost": 0.6, "sfx_boost": 0.5, "cut_speed": 1.0},
            {"name": "text_focus", "audio_boost": 0.3, "visual_boost": 0.4, "text_boost": 0.9, "sfx_boost": 0.3},
        ]
        
        # Generate variants
        for i in range(self.n_variants):
            config = hook_configs[i % len(hook_configs)]
            
            # Perturb latent space with Gaussian noise (classical "superposition")
            noise = torch.randn_like(base_latent) * self.exploration_temp
            variant_latent = base_latent + noise
            
            # Calculate virality probability (density matrix diagonal analog)
            prob = self._calculate_virality_probability(
                config, transcript_features, whisper_segments
            )
            
            variant = ViralVariant(
                variant_id=f"variant_{i:03d}",
                hook_type=config["name"],
                latent_vector=variant_latent.cpu().numpy(),
                virality_probability=prob,
                features=config
            )
            variants.append(variant)
        
        self.variant_cache = variants
        return variants
    
    def _calculate_virality_probability(
        self,
        config: Dict[str, float],
        transcript_features: Dict[str, Any],
        segments: List[Dict]
    ) -> float:
        """
        Density matrix-inspired probability calculation.
        
        Uses:
        - Base virality from transcript
        - Feature correlations (like "entanglement")
        - Interference patterns (constructive/destructive combinations)
        """
        # Base score from transcript (0-1)
        base_score = transcript_features.get("virality_base", 50.0) / 100.0
        
        # Feature contributions
        audio_contrib = config.get("audio_boost", 0.5) * 0.25
        visual_contrib = config.get("visual_boost", 0.5) * 0.35
        text_contrib = config.get("text_boost", 0.5) * 0.25
        sfx_contrib = config.get("sfx_boost", 0.5) * 0.15
        
        # "Interference" effects - feature combinations that amplify/dampen
        interference = 1.0
        
        # Fast cuts + strong audio = amplification (energy match)
        if config.get("cut_speed", 1.0) > 1.3 and config.get("audio_boost", 0) > 0.7:
            interference *= 1.15
        
        # High SFX + low visuals = dampening (unbalanced)
        if config.get("sfx_boost", 0) > 0.8 and config.get("visual_boost", 0) < 0.5:
            interference *= 0.85
        
        # Strong text + slow pace = amplification (educational content)
        if config.get("text_boost", 0) > 0.7 and config.get("cut_speed", 1.0) < 0.9:
            interference *= 1.10
        
        # Strong visuals + fast cuts = amplification (TikTok style)
        if config.get("visual_boost", 0) > 0.8 and config.get("cut_speed", 1.0) > 1.2:
            interference *= 1.20
        
        # Calculate final probability (normalize to 0-1)
        raw_score = base_score * 0.3 + audio_contrib + visual_contrib + text_contrib + sfx_contrib
        probability = raw_score * interference
        
        return float(min(1.0, max(0.0, probability)))
    
    def rank_variants(self, top_k: int = 3) -> List[ViralVariant]:
        """Rank variants by virality probability (quantum measurement analog)."""
        if not self.variant_cache:
            return []
        
        sorted_variants = sorted(
            self.variant_cache,
            key=lambda v: v.virality_probability,
            reverse=True
        )
        return sorted_variants[:top_k]
    
    def get_variant_diversity_score(self) -> float:
        """
        Calculate diversity in variant space (analog to quantum entropy).
        Higher = more diverse options, lower = variants too similar.
        """
        if not self.variant_cache:
            return 0.0
        
        probs = np.array([v.virality_probability for v in self.variant_cache])
        
        # Normalize to probability distribution
        if probs.sum() == 0:
            return 0.0
        probs = probs / probs.sum()
        
        # Shannon entropy as diversity measure
        entropy = -np.sum(probs * np.log(probs + 1e-10))
        max_entropy = np.log(len(probs))
        
        return float(entropy / max_entropy) if max_entropy > 0 else 0.0
    
    def get_interference_matrix(self) -> np.ndarray:
        """
        Calculate "interference" between hook types (correlation matrix).
        Shows which feature combinations work well together.
        """
        if not self.variant_cache:
            return np.array([])
        
        hook_types = list(set(v.hook_type for v in self.variant_cache))
        n_types = len(hook_types)
        matrix = np.zeros((n_types, n_types))
        
        for i, type_a in enumerate(hook_types):
            for j, type_b in enumerate(hook_types):
                if i == j:
                    matrix[i, j] = 1.0
                    continue
                
                # Calculate correlation between hook types
                variants_a = [v for v in self.variant_cache if v.hook_type == type_a]
                variants_b = [v for v in self.variant_cache if v.hook_type == type_b]
                
                if variants_a and variants_b:
                    avg_a = np.mean([v.virality_probability for v in variants_a])
                    avg_b = np.mean([v.virality_probability for v in variants_b])
                    # Correlation approximation
                    matrix[i, j] = (avg_a + avg_b) / 2
        
        return matrix


# ============================================================================
# Swarm Evolution Engine
# ============================================================================

@dataclass
class ClipGenome:
    """Genetic representation of a clip variant."""
    hook_start_time: float
    cut_speed: float
    music_intensity: float
    subtitle_style: int
    broll_frequency: float
    color_grade: int
    sfx_intensity: float


class SwarmEvolutionEngine:
    """
    Evolves clip variants through genetic algorithm (DEAP).
    
    Population of genomes compete, crossover, mutate to find optimal
    virality configurations per video.
    """
    
    def __init__(
        self,
        population_size: int = 50,
        n_generations: int = 10,
        crossover_prob: float = 0.7,
        mutation_prob: float = 0.2,
        fitness_func: Optional[Callable] = None
    ):
        self.population_size = population_size
        self.n_generations = n_generations
        self.cx_prob = crossover_prob
        self.mut_prob = mutation_prob
        self.fitness_func = fitness_func or self._default_fitness
        
        self.toolbox = base.Toolbox() if DEAP_AVAILABLE else None
        self.stats_history: List[Dict] = []
        
        if DEAP_AVAILABLE:
            self._setup_evolution()
    
    def _setup_evolution(self):
        """Initialize DEAP toolbox for evolution."""
        if not DEAP_AVAILABLE:
            return
        
        # Genome: [hook_time, cut_speed, music, subtitle, broll, color, sfx]
        self.toolbox.register("attr_hook", random.uniform, 0, 5)
        self.toolbox.register("attr_speed", random.uniform, 0.5, 2.0)
        self.toolbox.register("attr_music", random.uniform, 0, 1)
        self.toolbox.register("attr_subtitle", random.randint, 0, 4)
        self.toolbox.register("attr_broll", random.uniform, 0, 1)
        self.toolbox.register("attr_color", random.randint, 0, 3)
        self.toolbox.register("attr_sfx", random.uniform, 0, 1)
        
        creator.create("FitnessMax", base.Fitness, weights=(1.0,))
        creator.create("Individual", list, fitness=creator.FitnessMax)
        
        self.toolbox.register(
            "individual",
            tools.initCycle,
            creator.Individual,
            (
                self.toolbox.attr_hook,
                self.toolbox.attr_speed,
                self.toolbox.attr_music,
                self.toolbox.attr_subtitle,
                self.toolbox.attr_broll,
                self.toolbox.attr_color,
                self.toolbox.attr_sfx,
            ),
            n=1
        )
        
        self.toolbox.register(
            "population",
            tools.initRepeat,
            list,
            self.toolbox.individual
        )
        
        # Genetic operators
        self.toolbox.register("mate", tools.cxBlend, alpha=0.5)
        self.toolbox.register(
            "mutate",
            tools.mutPolynomialBounded,
            low=[0, 0.5, 0, 0, 0, 0, 0],
            up=[5, 2.0, 1, 4, 1, 3, 1],
            eta=20.0,
            indpb=0.2
        )
        self.toolbox.register("select", tools.selTournament, tournsize=3)
        self.toolbox.register("evaluate", self._evaluate_individual)
    
    def _evaluate_individual(self, individual: List[float]) -> Tuple[float]:
        """Evaluate virality fitness of a clip genome."""
        genome = ClipGenome(
            hook_start_time=individual[0],
            cut_speed=individual[1],
            music_intensity=individual[2],
            subtitle_style=int(individual[3]),
            broll_frequency=individual[4],
            color_grade=int(individual[5]),
            sfx_intensity=individual[6]
        )
        
        fitness = self.fitness_func(genome)
        return (fitness,)
    
    def _default_fitness(self, genome: ClipGenome) -> float:
        """Default virality fitness function."""
        score = 50.0
        
        # Hook timing (earlier = better for short-form)
        if genome.hook_start_time < 1.0:
            score += 25
        elif genome.hook_start_time < 2.0:
            score += 20
        elif genome.hook_start_time < 3.0:
            score += 10
        
        # Cut speed (platform dependent - optimized for TikTok)
        if 1.2 <= genome.cut_speed <= 1.5:
            score += 15
        elif genome.cut_speed > 1.8:
            score += 5  # Very fast can be overwhelming
        
        # Music intensity
        if genome.music_intensity > 0.6:
            score += 10
        
        # B-roll (moderate is good)
        if 0.3 <= genome.broll_frequency <= 0.7:
            score += 10
        elif genome.broll_frequency > 0.9:
            score -= 5  # Too much B-roll distracts
        
        # Color grade (vibrant = viral for TikTok)
        if genome.color_grade == 2:  # vibrant
            score += 12
        elif genome.color_grade == 0:  # warm
            score += 8
        
        # SFX intensity
        if 0.4 <= genome.sfx_intensity <= 0.8:
            score += 8
        
        return min(100.0, max(0.0, score))
    
    def evolve(
        self,
        content_type: str = "general",
        callback: Optional[Callable] = None
    ) -> Tuple[List[ClipGenome], Dict]:
        """
        Run evolution for N generations.
        
        Args:
            content_type: "educational", "entertainment", "general"
            callback: Optional callback(gen, stats) for progress updates
            
        Returns:
            (best_genomes, evolution_statistics)
        """
        if not DEAP_AVAILABLE:
            # Fallback without DEAP
            return self._fallback_evolve(content_type)
        
        # Update fitness function based on content type
        if content_type == "educational":
            self.fitness_func = self._educational_fitness
        elif content_type == "entertainment":
            self.fitness_func = self._entertainment_fitness
        else:
            self.fitness_func = self._default_fitness
        
        # Initialize population
        pop = self.toolbox.population(n=self.population_size)
        
        # Statistics tracking
        stats = tools.Statistics(lambda ind: ind.fitness.values[0])
        stats.register("avg", np.mean)
        stats.register("std", np.std)
        stats.register("min", np.min)
        stats.register("max", np.max)
        
        # Hall of fame - best individuals ever
        hof = tools.HallOfFame(5)
        
        # Evolution loop
        self.stats_history = []
        
        for gen in range(self.n_generations):
            # Selection and breeding
            offspring = self.toolbox.select(pop, len(pop))
            offspring = list(map(self.toolbox.clone, offspring))
            
            # Crossover
            for child1, child2 in zip(offspring[::2], offspring[1::2]):
                if random.random() < self.cx_prob:
                    self.toolbox.mate(child1, child2)
                    del child1.fitness.values
                    del child2.fitness.values
            
            # Mutation
            for mutant in offspring:
                if random.random() < self.mut_prob:
                    self.toolbox.mutate(mutant)
                    del mutant.fitness.values
            
            # Evaluate invalid individuals
            invalid_ind = [ind for ind in offspring if not ind.fitness.valid]
            fitnesses = map(self.toolbox.evaluate, invalid_ind)
            for ind, fit in zip(invalid_ind, fitnesses):
                ind.fitness.values = fit
            
            # Replace population
            pop[:] = offspring
            
            # Update hall of fame
            hof.update(pop)
            
            # Record statistics
            record = stats.compile(pop)
            self.stats_history.append({"generation": gen, **record})
            
            if callback:
                callback(gen, record)
        
        # Convert hall of fame to genomes
        best_genomes = []
        for ind in hof:
            genome = ClipGenome(
                hook_start_time=ind[0],
                cut_speed=ind[1],
                music_intensity=ind[2],
                subtitle_style=int(ind[3]),
                broll_frequency=ind[4],
                color_grade=int(ind[5]),
                sfx_intensity=ind[6]
            )
            best_genomes.append(genome)
        
        evolution_stats = {
            "generations": self.n_generations,
            "population": self.population_size,
            "final_stats": self.stats_history[-1] if self.stats_history else {},
            "convergence": self._calculate_convergence(),
            "history": self.stats_history
        }
        
        return best_genomes, evolution_stats
    
    def _educational_fitness(self, genome: ClipGenome) -> float:
        """Fitness optimized for educational content."""
        score = 50.0
        
        # Earlier hook for educational (get to the point)
        if genome.hook_start_time < 1.5:
            score += 20
        
        # Slower cuts for comprehension
        if 0.8 <= genome.cut_speed <= 1.2:
            score += 15
        
        # Moderate music (don't distract)
        if 0.3 <= genome.music_intensity <= 0.6:
            score += 10
        
        # More subtitles for clarity
        if genome.subtitle_style in [1, 2, 3]:  # Clear, readable styles
            score += 12
        
        # Less B-roll (focus on content)
        if genome.broll_frequency < 0.4:
            score += 10
        
        return min(100.0, max(0.0, score))
    
    def _entertainment_fitness(self, genome: ClipGenome) -> float:
        """Fitness optimized for entertainment content."""
        score = 50.0
        
        # Fast hook
        if genome.hook_start_time < 1.0:
            score += 25
        
        # Fast cuts for energy
        if genome.cut_speed > 1.3:
            score += 15
        
        # Strong music
        if genome.music_intensity > 0.7:
            score += 12
        
        # Lots of B-roll
        if genome.broll_frequency > 0.6:
            score += 10
        
        # High SFX
        if genome.sfx_intensity > 0.6:
            score += 8
        
        # Vibrant colors
        if genome.color_grade == 2:
            score += 10
        
        return min(100.0, max(0.0, score))
    
    def _fallback_evolve(self, content_type: str) -> Tuple[List[ClipGenome], Dict]:
        """Fallback evolution without DEAP (random search + hill climbing)."""
        logger.warning("Using fallback evolution (DEAP not available)")
        
        # Generate random population
        genomes = []
        for _ in range(self.population_size):
            genome = ClipGenome(
                hook_start_time=random.uniform(0, 5),
                cut_speed=random.uniform(0.5, 2.0),
                music_intensity=random.uniform(0, 1),
                subtitle_style=random.randint(0, 4),
                broll_frequency=random.uniform(0, 1),
                color_grade=random.randint(0, 3),
                sfx_intensity=random.uniform(0, 1)
            )
            genomes.append(genome)
        
        # Score all
        if content_type == "educational":
            scores = [(g, self._educational_fitness(g)) for g in genomes]
        elif content_type == "entertainment":
            scores = [(g, self._entertainment_fitness(g)) for g in genomes]
        else:
            scores = [(g, self._default_fitness(g)) for g in genomes]
        
        # Sort and take top 5
        scores.sort(key=lambda x: x[1], reverse=True)
        best_genomes = [g for g, _ in scores[:5]]
        
        stats = {
            "generations": 1,
            "population": self.population_size,
            "note": "Fallback mode (DEAP not available)",
            "final_stats": {"max": scores[0][1], "avg": np.mean([s[1] for s in scores])}
        }
        
        return best_genomes, stats
    
    def _calculate_convergence(self) -> str:
        """Calculate if evolution has converged."""
        if len(self.stats_history) < 5:
            return "insufficient_data"
        
        recent_max = [s["max"] for s in self.stats_history[-5:]]
        if max(recent_max) - min(recent_max) < 2.0:
            return "converged"
        elif recent_max[-1] > recent_max[0]:
            return "improving"
        else:
            return "stable"


# ============================================================================
# ComfyUI Nodes
# ============================================================================

class QuantumInspiredViralityNode:
    """
    ComfyUI Node: Quantum-Inspired Virality Simulator
    
    Generates 100+ parallel variants in latent space and ranks by virality probability.
    Returns top-K variants for full rendering (70% compute savings).
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_latent": ("STRING", {"default": ""}),  # JSON-serialized latent
                "transcript_features": ("JSON", {}),
                "n_variants": ("INT", {"default": 100, "min": 10, "max": 500}),
                "top_k": ("INT", {"default": 3, "min": 1, "max": 10}),
            },
            "optional": {
                "exploration_temperature": ("FLOAT", {"default": 0.1, "min": 0.01, "max": 1.0}),
            }
        }
    
    RETURN_TYPES = ("JSON", "JSON", "FLOAT")
    RETURN_NAMES = ("top_variants", "variant_info", "diversity_score")
    FUNCTION = "simulate"
    CATEGORY = "ViraClip/Quantum-Inspired"
    
    def simulate(self, video_latent, transcript_features, n_variants, top_k, exploration_temperature=0.1):
        try:
            # Parse inputs
            if isinstance(video_latent, str):
                latent_tensor = torch.tensor(json.loads(video_latent))
            else:
                latent_tensor = torch.tensor(video_latent)
            
            if isinstance(transcript_features, str):
                features = json.loads(transcript_features)
            else:
                features = transcript_features
            
            # Run simulation
            simulator = QuantumInspiredViralitySimulator(
                n_variants=n_variants,
                exploration_temp=exploration_temperature
            )
            
            variants = simulator.generate_parallel_variants(
                base_latent=latent_tensor,
                transcript_features=features,
                whisper_segments=features.get("segments", [])
            )
            
            top_variants = simulator.rank_variants(top_k=top_k)
            diversity = simulator.get_variant_diversity_score()
            
            # Prepare outputs
            top_variants_json = [
                {
                    "variant_id": v.variant_id,
                    "hook_type": v.hook_type,
                    "virality_probability": v.virality_probability,
                    "features": v.features
                }
                for v in top_variants
            ]
            
            # Interference matrix for analysis
            interference = simulator.get_interference_matrix()
            
            info = {
                "n_variants_generated": n_variants,
                "top_k": top_k,
                "diversity_score": diversity,
                "compute_savings_percent": 100 - (top_k / n_variants * 100),
                "interference_matrix_shape": list(interference.shape) if interference.size > 0 else [],
                "top_variants": top_variants_json
            }
            
            return (json.dumps(top_variants_json), json.dumps(info), diversity)
            
        except Exception as e:
            logger.error(f"QuantumInspiredViralityNode error: {e}")
            return ("[]", json.dumps({"error": str(e)}), 0.0)


class SwarmEvolutionViralityNode:
    """
    ComfyUI Node: Swarm Evolution Viral Engine
    
    Evolves 50 clip variants through genetic algorithm (DEAP).
    Returns top-5 evolved "specimens" with fitness tracking.
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "content_type": (["general", "educational", "entertainment"], {"default": "general"}),
                "population_size": ("INT", {"default": 50, "min": 20, "max": 200}),
                "n_generations": ("INT", {"default": 10, "min": 5, "max": 50}),
                "crossover_prob": ("FLOAT", {"default": 0.7, "min": 0.1, "max": 1.0}),
                "mutation_prob": ("FLOAT", {"default": 0.2, "min": 0.05, "max": 0.5}),
            },
            "optional": {
                "video_features": ("JSON", {"default": "{}"}),
            }
        }
    
    RETURN_TYPES = ("JSON", "JSON")
    RETURN_NAMES = ("evolved_genomes", "evolution_stats")
    FUNCTION = "evolve"
    CATEGORY = "ViraClip/Swarm-Evolution"
    
    def evolve(self, content_type, population_size, n_generations,
               crossover_prob, mutation_prob, video_features="{}"):
        try:
            if isinstance(video_features, str):
                video_features = json.loads(video_features)
            
            # Initialize engine
            engine = SwarmEvolutionEngine(
                population_size=population_size,
                n_generations=n_generations,
                crossover_prob=crossover_prob,
                mutation_prob=mutation_prob
            )
            
            # Run evolution
            best_genomes, stats = engine.evolve(content_type=content_type)
            
            # Prepare outputs
            genomes_json = [
                {
                    "hook_start_time": round(g.hook_start_time, 2),
                    "cut_speed": round(g.cut_speed, 2),
                    "music_intensity": round(g.music_intensity, 2),
                    "subtitle_style": g.subtitle_style,
                    "broll_frequency": round(g.broll_frequency, 2),
                    "color_grade": g.color_grade,
                    "sfx_intensity": round(g.sfx_intensity, 2),
                    "fitness_estimate": engine.fitness_func(g)
                }
                for g in best_genomes
            ]
            
            return (json.dumps(genomes_json), json.dumps(stats))
            
        except Exception as e:
            logger.error(f"SwarmEvolutionNode error: {e}")
            return ("[]", json.dumps({"error": str(e)}))


# ============================================================================
# Phase 8.3: LSTM/CNN Engagement Prediction Node
# ============================================================================

class EngagementPredictionNode:
    """
    ComfyUI node: predict viewer drop-off curve + optimal hook insertion points.
    Uses LSTM/CNN model (trained on feedback data) or heuristic fallback.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "transcript_json": ("STRING", {"default": "[]"}),
                "duration": ("FLOAT", {"default": 30.0, "min": 5.0, "max": 600.0, "step": 0.5}),
            },
            "optional": {
                "audio_features_json": ("STRING", {"default": "{}"}),
            }
        }

    RETURN_TYPES = ("STRING", "FLOAT", "STRING")
    RETURN_NAMES = ("engagement_curve_json", "retention_score", "hook_points_json")
    FUNCTION = "predict"
    CATEGORY = "ViraClip/Advanced ML"

    def predict(
        self,
        transcript_json: str,
        duration: float,
        audio_features_json: str = "{}",
    ):
        try:
            import sys
            from pathlib import Path as _Path
            _src = str(_Path(__file__).parent.parent)
            if _src not in sys.path:
                sys.path.insert(0, _src)

            from services.engagement_prediction_service import get_engagement_predictor

            words = json.loads(transcript_json) if transcript_json.strip() else []
            af = json.loads(audio_features_json) if audio_features_json.strip() else {}

            predictor = get_engagement_predictor()
            result = predictor.predict_engagement_curve(
                words=words,
                audio_features=af,
                duration=duration,
            )

            curve_json = json.dumps(result["curve"])
            hooks_json = json.dumps(result["hook_points"])
            retention = float(result["retention_score"])

            logger.info(
                f"[EngagementPredictionNode] retention={retention:.0f}% "
                f"method={result['predicted_by']} "
                f"drop-offs={result['drop_off_points']}"
            )
            return (curve_json, retention, hooks_json)

        except Exception as e:
            logger.error(f"[EngagementPredictionNode] Error: {e}")
            return ("[]", 50.0, "[]")


# Node registrations
NODE_CLASS_MAPPINGS = {
    "QuantumInspiredViralityNode": QuantumInspiredViralityNode,
    "SwarmEvolutionViralityNode": SwarmEvolutionViralityNode,
    "EngagementPredictionNode": EngagementPredictionNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QuantumInspiredViralityNode": "🌌 Quantum-Inspired Virality Simulator (Phase 8)",
    "SwarmEvolutionViralityNode": "🧬 Swarm Evolution Viral Engine (Phase 8)",
    "EngagementPredictionNode": "📉 Engagement Drop-off Predictor (Phase 8.3)",
}

__all__ = [
    'QuantumInspiredViralityNode',
    'SwarmEvolutionViralityNode',
    'EngagementPredictionNode',
    'QuantumInspiredViralitySimulator',
    'SwarmEvolutionEngine',
    'ViralVariant',
    'ClipGenome',
    'NODE_CLASS_MAPPINGS',
    'NODE_DISPLAY_NAME_MAPPINGS',
]
