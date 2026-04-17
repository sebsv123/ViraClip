"""
ViraClip Custom Nodes for ComfyUI
==================================

This package provides custom nodes for integrating ViraClip's viral video
pipeline into ComfyUI's visual workflow system.

Nodes Included:
- ViraClipWhisperNode: Transcription + virality scoring
- ViraClipYOLONode: Object detection for B-roll keywords
- ViraClipSilenceRemovalNode: Jump cuts / filler removal
- ViraClipThumbnailNode: Smart thumbnail selection
- ViraClipMetadataNode: SEO titles + hashtags generation
- ViraClipLoRATrainerNode: Train viral style LoRAs
- ViraClipDatasetPrepNode: Prepare datasets for training
- QuantumInspiredViralityNode: Quantum-inspired parallel variant simulation (Phase 8)
- SwarmEvolutionViralityNode: Genetic algorithm evolution engine (Phase 8)

Usage:
    1. Copy this folder to /ComfyUI/custom_nodes/viraclip_nodes
    2. Restart ComfyUI
    3. Find nodes in the "ViraClip" category

API Bridge:
    Use comfyui_bridge.py from ViraClip backend to execute
    workflows programmatically via FastAPI.

For more information, see:
    - ROADMAP.md (Phases 6, 7, 8, 9)
    - workflows/*.json (example workflows)
    - DEPLOY_GUIDE.md (deployment instructions)
"""

# Import all nodes for ComfyUI registration
try:
    from .viraclip_nodes import (
        ViraClipWhisperNode,
        ViraClipYOLONode,
        ViraClipSilenceRemovalNode,
        ViraClipThumbnailNode,
        ViraClipMetadataNode,
        NODE_CLASS_MAPPINGS as CORE_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as CORE_DISPLAY_MAPPINGS
    )
    
    from .viraclip_training_nodes import (
        ViraClipLoRATrainerNode,
        ViraClipDatasetPrepNode,
        NODE_CLASS_MAPPINGS as TRAIN_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as TRAIN_DISPLAY_MAPPINGS
    )
    
    from .viraclip_advanced_ml import (
        QuantumInspiredViralityNode,
        SwarmEvolutionViralityNode,
        NODE_CLASS_MAPPINGS as ADVANCED_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as ADVANCED_DISPLAY_MAPPINGS
    )
    
    # Merge mappings
    NODE_CLASS_MAPPINGS = {}
    NODE_CLASS_MAPPINGS.update(CORE_MAPPINGS)
    NODE_CLASS_MAPPINGS.update(TRAIN_MAPPINGS)
    NODE_CLASS_MAPPINGS.update(ADVANCED_MAPPINGS)
    
    NODE_DISPLAY_NAME_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS.update(CORE_DISPLAY_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(TRAIN_DISPLAY_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(ADVANCED_DISPLAY_MAPPINGS)
    
    __all__ = [
        'NODE_CLASS_MAPPINGS',
        'NODE_DISPLAY_NAME_MAPPINGS',
        'ViraClipWhisperNode',
        'ViraClipYOLONode',
        'ViraClipSilenceRemovalNode',
        'ViraClipThumbnailNode',
        'ViraClipMetadataNode',
        'ViraClipLoRATrainerNode',
        'ViraClipDatasetPrepNode',
        'QuantumInspiredViralityNode',
        'SwarmEvolutionViralityNode',
    ]
    
except ImportError as e:
    print(f"Warning: Could not import all ViraClip nodes: {e}")
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}

__version__ = "1.0.0"
__author__ = "ViraClip Team"
