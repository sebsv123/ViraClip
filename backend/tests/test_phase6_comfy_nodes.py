"""
Phase 6 — ComfyUI Custom Nodes Tests
=====================================
Verifies that all 9 ViraClip ComfyUI nodes are properly defined:
  Core:     ViraClipWhisperNode, YOLONode, SilenceRemovalNode,
            ThumbnailNode, MetadataNode
  Training: ViraClipLoRATrainerNode, DatasetPrepNode
  Advanced: QuantumInspiredViralityNode, SwarmEvolutionViralityNode
"""
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import torch

# ---------------------------------------------------------------------------
# Stub heavy optional deps so the nodes import cleanly without real models
# ---------------------------------------------------------------------------
for _mod in [
    "deap", "deap.base", "deap.creator", "deap.tools", "deap.algorithms",
    "ultralytics", "cv2", "mediapipe",
]:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from src.comfy_nodes.viraclip_nodes import (  # noqa: E402
    NODE_CLASS_MAPPINGS as CORE_MAPPINGS,
    ViraClipMetadataNode,
    ViraClipSilenceRemovalNode,
    ViraClipThumbnailNode,
    ViraClipWhisperNode,
    ViraClipYOLONode,
)
from src.comfy_nodes.viraclip_training_nodes import (  # noqa: E402
    LoRAConfig,
    NODE_CLASS_MAPPINGS as TRAIN_MAPPINGS,
    ViraClipDatasetPrepNode,
    ViraClipLoRATrainerNode,
)
from src.comfy_nodes.viraclip_advanced_ml import (  # noqa: E402
    NODE_CLASS_MAPPINGS as ADVANCED_MAPPINGS,
    QuantumInspiredViralityNode,
    QuantumInspiredViralitySimulator,
    SwarmEvolutionViralityNode,
    ViralVariant,
)
from src.comfy_nodes import NODE_CLASS_MAPPINGS  # noqa: E402


# ===========================================================================
# Section 1 — NODE_CLASS_MAPPINGS completeness
# ===========================================================================

class TestNodeRegistration:
    EXPECTED_CORE = {
        "ViraClipWhisperNode",
        "ViraClipYOLONode",
        "ViraClipSilenceRemovalNode",
        "ViraClipThumbnailNode",
        "ViraClipMetadataNode",
    }
    EXPECTED_TRAINING = {
        "ViraClipLoRATrainerNode",
        "ViraClipDatasetPrepNode",
    }
    EXPECTED_ADVANCED = {
        "QuantumInspiredViralityNode",
        "SwarmEvolutionViralityNode",
    }

    def test_core_nodes_registered(self):
        for name in self.EXPECTED_CORE:
            assert name in CORE_MAPPINGS, f"{name} missing from CORE_MAPPINGS"

    def test_training_nodes_registered(self):
        for name in self.EXPECTED_TRAINING:
            assert name in TRAIN_MAPPINGS, f"{name} missing from TRAIN_MAPPINGS"

    def test_advanced_nodes_registered(self):
        for name in self.EXPECTED_ADVANCED:
            assert name in ADVANCED_MAPPINGS, f"{name} missing from ADVANCED_MAPPINGS"

    def test_combined_mappings_has_all_nine(self):
        all_expected = (
            self.EXPECTED_CORE | self.EXPECTED_TRAINING | self.EXPECTED_ADVANCED
        )
        for name in all_expected:
            assert name in NODE_CLASS_MAPPINGS, f"{name} missing from combined NODE_CLASS_MAPPINGS"

    def test_all_mappings_point_to_classes(self):
        for name, cls in NODE_CLASS_MAPPINGS.items():
            assert isinstance(cls, type), f"{name} value must be a class"


# ===========================================================================
# Section 2 — ComfyUI contract: INPUT_TYPES / RETURN_TYPES / FUNCTION / CATEGORY
# ===========================================================================

def _assert_comfy_contract(node_cls):
    """Each ComfyUI node must expose the 4 required class attributes."""
    assert hasattr(node_cls, "INPUT_TYPES"), f"{node_cls.__name__} missing INPUT_TYPES"
    assert callable(node_cls.INPUT_TYPES), "INPUT_TYPES must be callable classmethod"
    it = node_cls.INPUT_TYPES()
    assert isinstance(it, dict) and "required" in it, "INPUT_TYPES must return {'required': {...}}"

    assert hasattr(node_cls, "RETURN_TYPES"), f"{node_cls.__name__} missing RETURN_TYPES"
    assert isinstance(node_cls.RETURN_TYPES, tuple), "RETURN_TYPES must be a tuple"

    assert hasattr(node_cls, "FUNCTION"), f"{node_cls.__name__} missing FUNCTION"
    assert isinstance(node_cls.FUNCTION, str), "FUNCTION must be a string"

    assert hasattr(node_cls, "CATEGORY"), f"{node_cls.__name__} missing CATEGORY"
    assert isinstance(node_cls.CATEGORY, str), "CATEGORY must be a string"


class TestComfyUIContract:
    @pytest.mark.parametrize("node_cls", [
        ViraClipWhisperNode,
        ViraClipYOLONode,
        ViraClipSilenceRemovalNode,
        ViraClipThumbnailNode,
        ViraClipMetadataNode,
        ViraClipLoRATrainerNode,
        ViraClipDatasetPrepNode,
        QuantumInspiredViralityNode,
        SwarmEvolutionViralityNode,
    ])
    def test_node_satisfies_comfyui_contract(self, node_cls):
        _assert_comfy_contract(node_cls)

    def test_all_nodes_in_viraclip_category(self):
        for node_cls in NODE_CLASS_MAPPINGS.values():
            assert "ViraClip" in node_cls.CATEGORY, (
                f"{node_cls.__name__}.CATEGORY should include 'ViraClip'"
            )


# ===========================================================================
# Section 3 — Whisper Node INPUT_TYPES content
# ===========================================================================

class TestWhisperNodeInputTypes:
    def test_required_fields(self):
        inputs = ViraClipWhisperNode.INPUT_TYPES()["required"]
        assert "video_path" in inputs
        assert "model_size" in inputs
        assert "device" in inputs

    def test_model_size_includes_large_v3(self):
        inputs = ViraClipWhisperNode.INPUT_TYPES()["required"]
        sizes = inputs["model_size"][0]  # list of choices
        assert "large-v3" in sizes

    def test_return_types_has_three_outputs(self):
        assert len(ViraClipWhisperNode.RETURN_TYPES) == 3


# ===========================================================================
# Section 4 — YOLO Node
# ===========================================================================

class TestYOLONode:
    def test_return_types(self):
        rt = ViraClipYOLONode.RETURN_TYPES
        assert len(rt) >= 1  # at least one output

    def test_required_video_path(self):
        inputs = ViraClipYOLONode.INPUT_TYPES()["required"]
        assert "video_path" in inputs


# ===========================================================================
# Section 5 — Silence Removal Node
# ===========================================================================

class TestSilenceRemovalNode:
    def test_required_inputs(self):
        inputs = ViraClipSilenceRemovalNode.INPUT_TYPES()["required"]
        assert "video_path" in inputs
        assert any("segment" in k or "json" in k.lower() or "words" in k for k in inputs)

    def test_output_has_video_path(self):
        rt = ViraClipSilenceRemovalNode.RETURN_TYPES
        assert "STRING" in rt


# ===========================================================================
# Section 6 — LoRA Config dataclass
# ===========================================================================

class TestLoRAConfig:
    def test_defaults(self):
        cfg = LoRAConfig()
        assert cfg.model_name == "Wan2.2-T2V-1.3B"
        assert cfg.lora_name == "viral_style"
        assert cfg.resolution == 512
        assert 1e-5 <= cfg.learning_rate <= 1e-3
        assert cfg.network_dim == 64

    def test_custom_values(self):
        cfg = LoRAConfig(num_epochs=20, batch_size=4)
        assert cfg.num_epochs == 20
        assert cfg.batch_size == 4


# ===========================================================================
# Section 7 — LoRA Trainer Node
# ===========================================================================

class TestLoRATrainerNode:
    def test_base_model_choices_include_wan22(self):
        inputs = ViraClipLoRATrainerNode.INPUT_TYPES()["required"]
        models = inputs["base_model"][0]
        assert any("Wan2.2" in m for m in models)

    def test_style_target_choices(self):
        inputs = ViraClipLoRATrainerNode.INPUT_TYPES()["required"]
        styles = inputs["style_target"][0]
        assert "tiktok_drama" in styles
        assert "mrbeast_energy" in styles

    def test_return_types(self):
        rt = ViraClipLoRATrainerNode.RETURN_TYPES
        assert len(rt) >= 2  # lora_path + training_info


# ===========================================================================
# Section 8 — Dataset Prep Node
# ===========================================================================

class TestDatasetPrepNode:
    def test_required_inputs(self):
        inputs = ViraClipDatasetPrepNode.INPUT_TYPES()["required"]
        assert "dataset_source" in inputs

    def test_dataset_source_choices(self):
        inputs = ViraClipDatasetPrepNode.INPUT_TYPES()["required"]
        sources = inputs["dataset_source"][0]
        assert "tiktok_hf" in sources or any("tiktok" in s for s in sources)


# ===========================================================================
# Section 9 — ViralVariant dataclass
# ===========================================================================

class TestViralVariant:
    def test_fields(self):
        vv = ViralVariant(
            variant_id="v1",
            hook_type="shock",
            latent_vector=np.zeros(128),
            virality_probability=0.75,
            features={"hook": 8.0},
        )
        assert vv.variant_id == "v1"
        assert vv.virality_probability == 0.75
        assert isinstance(vv.features, dict)


# ===========================================================================
# Section 10 — QuantumInspiredViralitySimulator
# ===========================================================================

class TestQuantumInspiredViralitySimulator:
    def _make_sim(self, n=10):
        return QuantumInspiredViralitySimulator(n_variants=n)

    def test_generate_variants_returns_list(self):
        sim = self._make_sim(n=5)
        base = torch.randn(128)
        variants = sim.generate_parallel_variants(
            base_latent=base,
            transcript_features={"hook_score": 7.5, "duration": 45},
        )
        assert isinstance(variants, list)
        assert len(variants) == 5

    def test_each_variant_has_probability(self):
        sim = self._make_sim(n=3)
        base = torch.randn(128)
        variants = sim.generate_parallel_variants(
            base_latent=base,
            transcript_features={},
        )
        for v in variants:
            assert 0.0 <= v.virality_probability <= 1.0

    def test_top_k_selection(self):
        sim = self._make_sim(n=20)
        base = torch.randn(128)
        variants = sim.generate_parallel_variants(
            base_latent=base,
            transcript_features={"hook_score": 9},
        )
        top = sorted(variants, key=lambda v: v.virality_probability, reverse=True)[:3]
        assert len(top) == 3
        # Best must be >= worst
        assert top[0].virality_probability >= top[-1].virality_probability


# ===========================================================================
# Section 11 — QuantumInspiredViralityNode ComfyUI wrapper
# ===========================================================================

class TestQuantumNodeWrapper:
    def test_contract(self):
        _assert_comfy_contract(QuantumInspiredViralityNode)

    def test_return_types_has_json_and_score(self):
        rt = QuantumInspiredViralityNode.RETURN_TYPES
        assert "STRING" in rt or "FLOAT" in rt

    def test_simulate_returns_tuple(self):
        node = QuantumInspiredViralityNode()
        latent = json.dumps(torch.randn(128).tolist())
        result = node.simulate(
            video_latent=latent,
            transcript_features={"hook_score": 8},
            n_variants=5,
            top_k=2,
        )
        assert isinstance(result, tuple)
        assert len(result) == 3
        # result[2] is the diversity score (FLOAT)
        assert isinstance(result[2], float)


# ===========================================================================
# Section 12 — SwarmEvolutionViralityNode
# ===========================================================================

class TestSwarmEvolutionNode:
    def test_contract(self):
        _assert_comfy_contract(SwarmEvolutionViralityNode)

    def test_evolve_returns_tuple(self):
        node = SwarmEvolutionViralityNode()
        result = node.evolve(
            content_type="general",
            population_size=10,
            n_generations=2,
            crossover_prob=0.7,
            mutation_prob=0.2,
        )
        assert isinstance(result, tuple)
        # Should have (evolved_genomes_json, evolution_stats_json)
        assert len(result) == 2


# ===========================================================================
# Section 13 — __init__.py combined mappings are consistent
# ===========================================================================

class TestPackageInit:
    def test_display_names_match_class_mappings(self):
        from src.comfy_nodes import NODE_DISPLAY_NAME_MAPPINGS
        # Every registered class should have a display name
        for key in NODE_CLASS_MAPPINGS:
            assert key in NODE_DISPLAY_NAME_MAPPINGS, (
                f"{key} in NODE_CLASS_MAPPINGS but not in NODE_DISPLAY_NAME_MAPPINGS"
            )

    def test_version_string_present(self):
        import src.comfy_nodes as pkg
        assert hasattr(pkg, "__version__")
        assert isinstance(pkg.__version__, str)
