# Plan de Reorganización — `backend/src/services/`

## Objetivo
Pasar de **104 archivos planos** en `services/` a una estructura por **dominios** donde cada carpeta agrupa código por responsabilidad, no por "es un servicio".

## Estructura objetivo

```
backend/src/
├── core/                       # infraestructura transversal
│   ├── cache_manager.py
│   ├── concurrency_optimizer.py
│   ├── error_handler.py
│   ├── metrics_service.py
│   ├── observability.py
│   └── enhanced_tracking_service.py
│
├── domains/
│   ├── ai/                     # LLMs, visión, editorial
│   │   ├── ai_prompts.py
│   │   ├── ai_thumbnail_service.py
│   │   ├── editorial_brain.py
│   │   ├── elite_ai_service.py
│   │   ├── llm_router.py
│   │   ├── llm_service.py
│   │   ├── llm_service_improved.py
│   │   ├── phi3_virality_service.py
│   │   ├── rag_memory.py
│   │   ├── subagent_pipeline.py
│   │   └── vision_service.py
│   │
│   ├── video/                  # procesado core de vídeo
│   │   ├── video_service.py           (144KB — candidato a split futuro)
│   │   ├── video_compression.py
│   │   ├── video_effects.py
│   │   ├── video_polish_service.py
│   │   ├── composite_engine.py
│   │   ├── background_composite_service.py
│   │   ├── lut_service.py
│   │   ├── vfx_service.py
│   │   ├── optical_flow_service.py
│   │   ├── scene_analyzer.py
│   │   ├── cut_zoom_service.py
│   │   ├── jump_cut_service.py
│   │   ├── speed_control_service.py
│   │   ├── transition_selector.py
│   │   └── variant_generator.py
│   │
│   ├── audio/                  # audio, música, SFX, voz
│   │   ├── audio_analysis.py
│   │   ├── audio_denoiser.py
│   │   ├── audio_ducking_service.py
│   │   ├── audio_recommendation.py
│   │   ├── background_music_service.py
│   │   ├── beat_sync_service.py
│   │   ├── clap_sfx_service.py
│   │   ├── freesound_service.py
│   │   ├── smart_audio.py
│   │   ├── sound_design_service.py
│   │   ├── tts_service.py
│   │   └── voice_synthesis.py
│   │
│   ├── broll/                  # b-roll & generación visual
│   │   ├── broll_compositor.py
│   │   ├── broll_effects_engine.py
│   │   ├── broll_service.py
│   │   ├── enhanced_broll_service.py
│   │   ├── contextual_broll.py
│   │   ├── scene_broll_placer.py
│   │   ├── semantic_broll_service.py
│   │   ├── t2v_broll_service.py
│   │   ├── ltxv_intro_service.py
│   │   ├── hook_visual_service.py
│   │   ├── image_gen_service.py
│   │   ├── google_imagen_service.py
│   │   ├── replicate_service.py
│   │   ├── stability_service.py
│   │   ├── pexels_service.py
│   │   ├── comfyui_integration.py
│   │   ├── comfyui_bridge.py
│   │   ├── overlay_content_source.py
│   │   └── contextual_overlay_engine.py
│   │
│   ├── captions/               # subtítulos & traducción
│   │   ├── caption_service.py
│   │   ├── confidence_subtitle_service.py
│   │   ├── translation_service.py
│   │   └── multilanguage_service.py
│   │
│   ├── detection/              # CV/ML detección
│   │   ├── face_detection_service.py
│   │   ├── face_tracking_service.py
│   │   ├── person_segmentation.py
│   │   ├── yolo_detector.py
│   │   ├── multimodal_detector.py
│   │   └── visual_keyword_detector.py
│   │
│   ├── virality/               # scoring, predicción, hooks
│   │   ├── viral_scorer_service.py
│   │   ├── viral_metadata_service.py
│   │   ├── viral_templates.py
│   │   ├── viral_trend_service.py
│   │   ├── virality_engine.py
│   │   ├── ml_virality_predictor.py
│   │   ├── engagement_prediction_service.py
│   │   ├── recommendation_engine.py
│   │   ├── clip_intelligence.py
│   │   ├── hook_engine.py
│   │   └── hook_reorder.py
│   │
│   ├── publishing/             # social, distribución, scheduling
│   │   ├── social_distribution_service.py
│   │   ├── social_publisher.py
│   │   ├── auto_scheduler.py
│   │   └── performance_webhook_service.py
│   │
│   ├── notifications/          # email
│   │   ├── email_service.py
│   │   ├── subscription_email_service.py
│   │   └── task_completion_email_service.py
│   │
│   ├── billing/                # pagos & suscripciones
│   │   └── billing_service.py
│   │
│   ├── feedback/               # feedback loops, learning, training
│   │   ├── feedback_loop_service.py
│   │   ├── learning_loop.py
│   │   ├── ab_testing_service.py
│   │   ├── competitor_analysis.py
│   │   ├── dataset_collector.py
│   │   ├── lora_training_service.py
│   │   └── creator_profile_service.py
│   │
│   ├── autopilot/              # orquestación & pipelines
│   │   ├── autopilot_service.py
│   │   ├── orchestrator.py
│   │   ├── workflow_automation.py
│   │   ├── creative_pipeline.py
│   │   └── task_service.py        (72KB — candidato a split)
│   │
│   ├── validation/             # QA & health checks
│   │   ├── clip_validator.py
│   │   ├── clip_health_service.py
│   │   └── quality_validator.py
│   │
│   ├── thumbnails/
│   │   └── thumbnail_service.py
│   │
│   └── upscaling/
│       └── upscaling_service.py
│
├── api/                         # routes (ya existe)
├── workers/                     # arq workers (ya existe)
├── repositories/                # DB access (ya existe)
├── models/                      # pydantic/DB models (ya existe)
├── agents/                      # agent pipelines (ya existe)
└── utils/                       # utilities (ya existe)
```

## Reglas de migración

1. **Un dominio por commit** → fácil revertir si algo falla
2. **Usar `git mv`** → preserva historial
3. **Actualizar imports** con script automático (regex + AST)
4. **Test entre cada dominio**:
   - `docker compose up -d backend worker`
   - Verificar `docker logs viraclip-backend | grep -i error`
   - Smoke test: `curl localhost:8000/health/db`
5. **`__init__.py`** en cada dominio (vacío está bien de inicio)
6. **`services/` sigue existiendo** temporalmente como re-export para compatibilidad durante la migración

## Orden de ejecución sugerido

Empezar por dominios con menos acoplamiento externo:

1. `notifications/` (3 archivos, bajo riesgo)
2. `billing/` (1 archivo)
3. `thumbnails/`, `upscaling/` (1 archivo cada uno)
4. `captions/` (4 archivos)
5. `detection/` (6 archivos)
6. `publishing/` (4 archivos)
7. `validation/` (3 archivos)
8. `audio/` (12 archivos)
9. `virality/` (11 archivos)
10. `feedback/` (7 archivos)
11. `video/` (15 archivos) — **más acoplado, revisar con cuidado**
12. `broll/` (19 archivos) — **muchos interdependientes**
13. `ai/` (11 archivos) — **usado por todos**
14. `autopilot/` (5 archivos) — **orquesta todo**
15. `core/` (6 archivos de infraestructura)

## Archivos que requieren atención especial

- **`video_service.py` (144KB)** — monolito. Post-migración debería dividirse en: `video_service.py` (core), `video_editor.py` (transformaciones), `video_renderer.py` (export).
- **`task_service.py` (72KB)** — igual, dividir en `task_orchestrator.py`, `task_state_machine.py`, `task_persistence.py`.
- **`creative_pipeline.py` (32KB)** — revisar si pertenece a `autopilot/` o es un dominio propio.

## Estimación

- Fase 4a (migración mecánica): **2-3 horas**
- Fase 4b (splits de monolitos grandes): **4-6 horas** adicionales opcionales

## Comando para actualizar imports

Un script Python con `ast` hace la refactorización automática:
```
for each moved file: services/X.py -> domains/Y/X.py
  replace "from src.services.X" → "from src.domains.Y.X"
  replace "from .services.X"    → "from .domains.Y.X"
  replace "import src.services.X as"  → "import src.domains.Y.X as"
```
