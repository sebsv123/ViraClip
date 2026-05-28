# VPI Editorial Preflight

- Generated: `2026-05-28T22:32:24Z`
- Status: `PASS`
- Ready for render: `true`

## Steps

- `offline_editorial_eval`: `PASS` (`returncode=0`)
- `composition_pack`: `PASS` (`returncode=0`)
- `composition_runtime_integration`: `PASS` (`returncode=0`)
- `motion_pack`: `PASS` (`returncode=0`)
- `caption_overlay_pack`: `PASS` (`returncode=0`)
- `broll_editorial_pack`: `PASS` (`returncode=0`)
- `editorial_runtime_integration`: `PASS` (`returncode=0`)
- `retention_editing_system`: `PASS` (`returncode=0`)
- `premium_runtime_contract`: `PASS` (`returncode=0`)
- `py_compile`: `PASS` (`returncode=0`)

## Output Tails

### offline_editorial_eval

```text
[frame-rhythm] kickframes=5->10 intent=risk_warning reason=hook_first3
[motion-pack] hook_intent=risk_warning visual_profile=tension_push
[motion-pack] scale_start=1.000 scale_end=1.050 frames=12
[motion-pack] contextual=true reason=hook_intent
[motion-pack] hook_intent=risk_warning visual_profile=tension_push
[motion-pack] scale_start=1.000 scale_end=1.050 frames=12
[motion-pack] contextual=true reason=hook_intent
[frame-rhythm] kickframes=5->10 intent=risk_warning reason=hook_first3
[visual-effects] intent_aware_effect type=punch_zoom intent=risk_warning status=strong score=7
[motion-pack] applied=true contextual_actions=tension_push
[editing-richness] motion_pack=true
[editing-richness] premium_visual_effect=true reason=contextual_motion_pack
[vfx-qc] type=contextual_emphasis premium=true reason=intent_aware_risk_warning_motion_pack
[offline-eval] case=T_motion_pack_risk_warning status=PASS reason=risk warning receives tension push and 5->10 kickframe rhythm
[motion-pack] hook_intent=neutral_explanation visual_profile=basic_clean_motion
[motion-pack] scale_start=1.000 scale_end=1.015 frames=12
[motion-pack] contextual=false reason=minimal_neutral_motion
[motion-pack] hook_intent=neutral_explanation visual_profile=basic_clean_motion
[motion-pack] scale_start=1.000 scale_end=1.015 frames=12
[motion-pack] contextual=false reason=minimal_neutral_motion
[frame-rhythm] skipped reason=no_editorial_moment
[visual-effects] intent_aware_effect type=subtle_push_in intent=neutral_explanation status=strong score=7
[motion-pack] applied=false contextual_actions=none
[editing-richness] motion_pack=false
[editing-richness] premium_visual_effect=false reason=basic_or_no_contextual_motion
[vfx-qc] type=basic_motion premium=false reason=generic_push_in
[offline-eval] case=U_motion_pack_generic_basic status=PASS reason=generic explanation stays basic motion and does not inflate premium visual effect
[caption-overlay] keyword_emphasis applied=true words=alivio|familia
[caption-overlay] hook_overlay applied=true text="No va de miedo" duration=1.1
[caption-overlay] density_guard action=skip_icon reason=too_many_elements
[caption-overlay] density_guard action=delay reason=too_many_elements
[caption-overlay] lower_third applied=true text=Seguro de decesos
[caption-overlay] pack_applied=true actions=keyword_emphasis|hook_overlay|lower_third
[editing-richness] caption_overlay_pack=true reason=caption_overlay_actions
[offline-eval] case=V_caption_overlay_pack_decesos status=PASS reason=caption overlay pack applies restrained keyword emphasis and hook overlay
[broll-editorial] should_use=true intent=emotional_support confidence=0.65 reason=soft_emotional_support
[broll-editorial] timing start_offset=2.40 duration=1.00 reason=emotional_pause
[broll-asset] intent=emotional_support matched=true asset=assets/broll/family_protection/01.mp4
[offline-eval] case=W_broll_editorial_pack status=PASS reason=editorial broll intent mapped and local asset matched without lugubrious cue
[offline-eval] score=1.000 status=READY_FOR_RENDER
```

### composition_pack

```text
PASS risk_warning mode: {'composition_pack': True, 'mode': 'warning_tension', 'composition_mode': 'warning_tension', 'screen_priority': 'face', 'max_layers': 2, 'max_simultaneous_layers': 2, 'priority_order': ['face', 'caption', 'hook_overlay', 'sfx'], 'reason': 'risk_warning keeps face visible, caption secondary, hook overlay only if needed', 'intent': 'risk_warning', 'contextual': True, 'visual_profile': ''}
PASS risk_warning max layers: 2
PASS risk_warning lower_third blocked with hook: ['hook_overlay', 'caption']
PASS myth_flip mode: {'composition_pack': True, 'mode': 'hook_driven', 'composition_mode': 'hook_driven', 'screen_priority': 'hook_overlay', 'max_layers': 2, 'max_simultaneous_layers': 2, 'priority_order': ['hook_overlay', 'caption', 'face'], 'reason': 'myth_flip needs hook overlay first, then caption support', 'intent': 'myth_flip', 'contextual': True, 'visual_profile': ''}
PASS myth_flip sweep allowed: {'allowed_layers': [{'type': 'sweeping_reveal', 'start_s': 0.2}, {'type': 'caption', 'start_s': 0.7}], 'skipped_layers': [], 'layers_final': ['sweeping_reveal', 'caption'], 'layer_overload': False, 'composition_decision_applied': True, 'conflicts_resolved_count': 0}
PASS emotional_closure mode: {'composition_pack': True, 'mode': 'emotional_soft', 'composition_mode': 'emotional_soft', 'screen_priority': 'face', 'max_layers': 2, 'max_simultaneous_layers': 2, 'priority_order': ['face', 'caption', 'music'], 'reason': 'emotional_closure keeps face visible, caption soft, no aggressive layers; WARNING: aggressive SFX conflicts with emotional_soft', 'intent': 'emotional_closure', 'contextual': True, 'visual_profile': ''}
PASS emotional_closure deep_boom blocked: {'allowed_layers': [{'type': 'caption', 'start_s': 1.0}], 'skipped_layers': [{'type': 'deep_boom', 'start_s': 0.5, 'reason': 'boom_in_emotional_closure', 'index': 0}], 'layers_final': ['caption'], 'layer_overload': False, 'composition_decision_applied': True, 'conflicts_resolved_count': 1}
PASS long caption icon skipped: {'allowed_layers': [{'type': 'caption', 'start_s': 0.6}], 'skipped_layers': [{'type': 'icon', 'text': 'este caption es demasiado largo para convivir con un icono sobrio en pantalla', 'start_s': 0.5, 'reason': 'long_caption_with_icon', 'index': 0}], 'layers_final': ['caption'], 'layer_overload': False, 'composition_decision_applied': True, 'conflicts_resolved_count': 1}
PASS business_punch mode: {'composition_pack': True, 'mode': 'business_punch', 'composition_mode': 'business_punch', 'screen_priority': 'caption', 'max_layers': 3, 'max_simultaneous_layers': 3, 'priority_order': ['caption', 'motion', 'sfx'], 'reason': 'business_punch allows up to 3 layers for punchy emphasis', 'intent': 'autonomous_business_stakes', 'contextual': True, 'visual_profile': ''}
PASS business_punch allows 3 layers: {'allowed_layers': [{'type': 'caption', 'start_s': 0.4}, {'type': 'motion', 'start_s': 0.2}, {'type': 'sfx', 'start_s': 0.5}], 'skipped_layers': [], 'layers_final': ['caption', 'motion', 'sfx'], 'layer_overload': False, 'composition_decision_applied': True, 'conflicts_resolved_count': 0}
PASS minimal_safe mode: {'composition_pack': True, 'mode': 'minimal_safe', 'composition_mode': 'minimal_safe', 'screen_priority': 'caption', 'max_layers': 1, 'max_simultaneous_layers': 1, 'priority_order': ['caption', 'face'], 'reason': 'neutral_explanation uses minimal layers, caption only', 'intent': 'neutral_explanation', 'contextual': False, 'visual_profile': ''}
PASS minimal_safe review/fail on weak first3: {'first3_visual_contract': {'hook_visible_before_1_5s': False, 'caption_readable': True, 'face_not_obstructed': True, 'no_layer_overload': True, 'motion_contextual': False}, 'first3_visual_passed': False, 'first3_visual_fail_count': 2, 'status': 'review', 'failed_checks': ['hook_visible_before_1_5s', 'motion_contextual'], 'downgrade_required': True}
RESULTS 12 PASS / 0 FAIL
```

### composition_runtime_integration

```text
00:32:22 [INFO] [composition-pack] mode=hook_driven priority=hook_overlay max_layers=2
00:32:22 [INFO] [composition-pack] reason=myth_flip needs hook overlay first, then caption support
00:32:22 [INFO] [first3-visual] hook_visible_before_1_5s=true
00:32:22 [INFO] [first3-visual] caption_readable=true
00:32:22 [INFO] [first3-visual] face_not_obstructed=true
00:32:22 [INFO] [first3-visual] no_layer_overload=true
00:32:22 [INFO] [first3-visual] motion_contextual=true
00:32:22 [INFO] [first3-visual] status=pass
00:32:22 [INFO] [first3-visual] private_premium_downgrade=false reason=none
00:32:22 [INFO] [composition-runtime] ✅ PASS  first3_visual_passed=True when all checks pass — passed=True fail_count=0
00:32:22 [INFO] [composition-runtime] ✅ PASS  first3_visual_fail_count=0 when all checks pass — fail_count=0
00:32:22 [INFO] [first3-visual] hook_visible_before_1_5s=false
00:32:22 [INFO] [first3-visual] caption_readable=true
00:32:22 [INFO] [first3-visual] face_not_obstructed=true
00:32:22 [INFO] [first3-visual] no_layer_overload=true
00:32:22 [INFO] [first3-visual] motion_contextual=false
00:32:22 [INFO] [first3-visual] status=review
00:32:22 [INFO] [first3-visual] private_premium_downgrade=true reason=hook_visible_before_1_5s|motion_contextual
00:32:22 [INFO] [composition-runtime] ✅ PASS  first3_visual_fail_count >= 2 when multiple checks fail — fail_count=2
00:32:22 [INFO] [composition-runtime] ✅ PASS  first3_visual_passed=False when 2+ failures — passed=False
00:32:22 [INFO] [composition-runtime] ✅ PASS  first3_contract_failed=True when fail_count >= 2 — fail_count=2
00:32:22 [INFO] [composition-runtime] ✅ PASS  status downgraded to PRIVATE_PREMIUM_REVIEW when first3_visual_contract fails — status=PRIVATE_PREMIUM_REVIEW editorial_quality=review_first3_visual_contract
00:32:22 [INFO] [composition-runtime] ✅ PASS  editorial_quality=review_first3_visual_contract when downgraded — editorial_quality=review_first3_visual_contract
00:32:22 [INFO] 
00:32:22 [INFO] ══════════════════════════════════════════════════════════════════════
00:32:22 [INFO] [composition-runtime] TEST 6: composition_pack=true only when real composition decisions
00:32:22 [INFO] [composition-runtime] Verifies CAMBIO 6: richness uses real composition
00:32:22 [INFO] ──────────────────────────────────────────────────────────────────────
00:32:22 [INFO] [composition-pack] mode=hook_driven priority=hook_overlay max_layers=2
00:32:22 [INFO] [composition-pack] reason=myth_flip needs hook overlay first, then caption support
00:32:22 [INFO] [composition-runtime] ✅ PASS  composition_pack_active=True when valid composition_mode exists — composition_mode=hook_driven
00:32:22 [INFO] [composition-runtime] ✅ PASS  composition_pack_active=False when runtime did not apply composition — composition_mode=hook_driven runtime_applied=False
00:32:22 [INFO] [composition-runtime] ✅ PASS  composition_pack_active=False when no composition_mode — composition_mode=None
00:32:22 [INFO] [composition-runtime] ✅ PASS  composition_pack_active=False when composition_mode=unknown — composition_mode=unknown
00:32:22 [INFO] [composition-runtime] ✅ PASS  composition_pack_active=False when composition_mode='' — composition_mode=''
00:32:22 [INFO] 
00:32:22 [INFO] ══════════════════════════════════════════════════════════════════════
00:32:22 [INFO] [composition-runtime] RESULTS: 41 PASS / 0 FAIL / 41 TOTAL
00:32:22 [INFO] ══════════════════════════════════════════════════════════════════════
00:32:22 [INFO] [composition-runtime] ✅ All tests PASSED
```

### motion_pack

```text
        },
        "sfx": {
          "sfx_motion_sync_applied": false,
          "sfx_motion_sync_type": "",
          "sfx_motion_sync_asset_type": "",
          "sfx_motion_sync_reason": "no_motion_sfx_needed",
          "aggressive_impact_allowed": false,
          "sfx_motion_sync_available": false,
          "composition_decision_applied": false
        },
        "events": [
          {
            "type": "subtle_push_in",
            "visual_profile": "basic_clean_motion",
            "start_s": 0.3,
            "duration_s": 0.4,
            "duration_frames": 12,
            "scale_start": 1.0,
            "scale": 1.015,
            "scale_end": 1.015,
            "easing": "smooth",
            "hold_frames": 0,
            "motion_pack_contextual": false,
            "motion_pack_profile": "basic_clean_motion",
            "motion_pack_applied": false,
            "kickframe_rhythm": null,
            "reason": "intent_aware_neutral_explanation_motion_pack",
            "visual_effect_classification": "basic_motion",
            "premium_visual_effect": false,
            "motion_pack_contextual_actions": []
          }
        ]
      },
      "expected": {
        "visual_profile": "basic_clean_motion",
        "premium_visual_effect": false
      }
    }
  ]
}
```

### caption_overlay_pack

```text
      }
    },
    {
      "case": "normal_subtitles_only",
      "status": "PASS",
      "passed": true,
      "actual": {
        "plan": {
          "caption_overlay_pack": false,
          "caption_overlay_actions": [],
          "keyword_emphasis_applied": false,
          "keyword_emphasis_terms": [],
          "hook_overlay": {
            "applied": false,
            "reason": "no_hook_text"
          },
          "caption_icon": {
            "applied": false,
            "concept": "",
            "reason": "not_useful"
          },
          "lower_third": {
            "applied": false,
            "reason": "branding_conflict"
          },
          "caption_start_s": 0.0,
          "density_guard_actions": [],
          "composition_allowed_layers": [],
          "composition_skipped_layers": [],
          "composition_decision_applied": false,
          "layer_overload": false,
          "caption_overlay_pack_reason": "normal_subtitles_only"
        }
      },
      "expected": {
        "caption_overlay_pack": false
      }
    }
  ]
}
```

### broll_editorial_pack

```text
[debug-broll-editorial-pack] decesos_intent=PASS {'should_use_broll': True, 'broll_intent': 'emotional_support', 'moment_type': 'emotional_pause', 'start_offset': 2.4, 'duration': 1.0, 'reason': 'soft_emotional_support', 'confidence': 0.65, 'fallback': 'motion_only', 'composition_allowed': True, 'skip_reason': ''}
[debug-broll-editorial-pack] decesos_no_fail_without_asset=PASS local_asset_match
[debug-broll-editorial-pack] decesos_not_lugubrious=PASS assets/broll/family_protection/01.mp4
[debug-broll-editorial-pack] salud_intent=PASS {'should_use_broll': True, 'broll_intent': 'risk_warning_context', 'moment_type': 'risk_phrase', 'start_offset': 1.6, 'duration': 1.2, 'reason': 'risk_context_support', 'confidence': 0.76, 'fallback': 'motion_only', 'composition_allowed': True, 'skip_reason': ''}
[debug-broll-editorial-pack] salud_timing_after_hook=PASS 1.6
[debug-broll-editorial-pack] autonomos_intent=PASS {'should_use_broll': True, 'broll_intent': 'autonomous_work_stability', 'moment_type': 'topic_shift', 'start_offset': 1.7, 'duration': 1.6, 'reason': 'business_stability_context', 'confidence': 0.82, 'fallback': 'motion_only', 'composition_allowed': True, 'skip_reason': ''}
[debug-broll-editorial-pack] autonomos_fallback_clean=PASS motion_only
[debug-broll-editorial-pack] autonomos_asset_optional=PASS True
[debug-broll-editorial-pack] practical_intent=PASS {'should_use_broll': True, 'broll_intent': 'practical_explanation', 'moment_type': 'explanation_example', 'start_offset': 2.0, 'duration': 1.5, 'reason': 'abstract_explanation_needs_visual_clarity', 'confidence': 0.72, 'fallback': 'motion_only', 'composition_allowed': True, 'skip_reason': ''}
[debug-broll-editorial-pack] practical_duration_range=PASS 1.5
[debug-broll-editorial-pack] emotional_soft_intent=PASS {'should_use_broll': True, 'broll_intent': 'emotional_support', 'moment_type': 'emotional_pause', 'start_offset': 2.4, 'duration': 1.0, 'reason': 'soft_emotional_support', 'confidence': 0.65, 'fallback': 'motion_only', 'composition_allowed': True, 'skip_reason': ''}
[debug-broll-editorial-pack] emotional_soft_not_aggressive=PASS {'should_use_broll': True, 'broll_intent': 'emotional_support', 'moment_type': 'emotional_pause', 'start_offset': 2.4, 'duration': 1.0, 'reason': 'soft_emotional_support', 'confidence': 0.65, 'fallback': 'motion_only', 'composition_allowed': True, 'skip_reason': ''}
[debug-broll-editorial-pack] minimal_safe_skip=PASS {'should_use_broll': False, 'broll_intent': 'no_broll_needed', 'moment_type': 'none', 'start_offset': 1.8, 'duration': 1.4, 'reason': 'no_editorial_gain', 'confidence': 0.2, 'fallback': 'none', 'composition_allowed': False, 'skip_reason': 'composition_conflict'}
[debug-broll-editorial-pack] composition_conflict_blocks_broll=PASS ['hook_overlay', 'caption']
[debug-broll-editorial-pack] no_assets_case_has_asset=PASS assets/broll/risk_warning/01.mp4
[debug-broll-editorial-pack] runtime_false_without_applied_asset_match=PASS False
[debug-broll-editorial-pack] runtime_false_when_composition_blocked=PASS False
[debug-broll-editorial-pack] results=17 PASS / 0 FAIL
```

### editorial_runtime_integration

```text
00:32:23 [INFO] [editorial-runtime] ✅ PASS  hook_fit_acceptable is bool — acceptable=True
00:32:23 [INFO] [editorial-runtime]   fit: acceptable=true score=1.00 reason=strong_emotional_closure_match
00:32:23 [INFO] 
00:32:23 [INFO] ════════════════════════════════════════════════════════════
00:32:23 [INFO] [editorial-runtime] SCENARIO 4: Weak hook + no editorial action → blocked 'rich'
00:32:23 [INFO] [editorial-runtime] Simulates the FASE 5 Quality Gate logic
00:32:23 [INFO] ────────────────────────────────────────────────────────────
00:32:23 [INFO] [editorial-runtime] ✅ PASS  weak hook blocked 'good' → 'acceptable' — status=acceptable
00:32:23 [INFO] [editorial-runtime] ✅ PASS  rich_blocked warning added — warnings=['rich_blocked_weak_hook_no_editorial_action']
00:32:23 [INFO] [editorial-runtime]   hook_first3_score=3 has_editorial_action=false → status=acceptable
00:32:23 [INFO] [editorial-runtime] ✅ PASS  strong hook + action keeps 'rich' — status=rich hook_score=7 has_action=True
00:32:23 [INFO] [editorial-runtime]   strong hook: score=7 has_action=true → status=rich (should be 'rich')
00:32:23 [INFO] 
00:32:23 [INFO] ════════════════════════════════════════════════════════════
00:32:23 [INFO] [editorial-runtime] SCENARIO 5: Intent-aware visual effects selection
00:32:23 [INFO] [editorial-runtime] Simulates FASE 6 logic from vpi_visual_effects_service
00:32:23 [INFO] ────────────────────────────────────────────────────────────
00:32:23 [INFO] [motion-pack] hook_intent=risk_warning visual_profile=tension_push
00:32:23 [INFO] [motion-pack] scale_start=1.000 scale_end=1.050 frames=12
00:32:23 [INFO] [motion-pack] contextual=true reason=hook_intent
00:32:23 [INFO] [motion-pack] hook_intent=risk_warning visual_profile=tension_push
00:32:23 [INFO] [motion-pack] scale_start=1.000 scale_end=1.050 frames=12
00:32:23 [INFO] [motion-pack] contextual=true reason=hook_intent
00:32:23 [INFO] [frame-rhythm] kickframes=5->10 intent=risk_warning reason=hook_first3
00:32:23 [INFO] [visual-effects] intent_aware_effect type=punch_zoom intent=risk_warning status=READY score=7
00:32:23 [INFO] [motion-pack] applied=true contextual_actions=tension_push
00:32:23 [INFO] [editing-richness] motion_pack=true
00:32:23 [INFO] [editing-richness] premium_visual_effect=true reason=contextual_motion_pack
00:32:23 [INFO] [vfx-qc] type=contextual_emphasis premium=true reason=intent_aware_risk_warning_motion_pack
00:32:23 [INFO] [vfx-qc] type=contextual_emphasis premium=true reason=speaker_focus_no_broll
00:32:23 [INFO] [editorial-runtime] ✅ PASS  plan_visual_effects returns list — type=list
00:32:23 [INFO] [editorial-runtime]   visual_effects_events=2
00:32:23 [INFO] [editorial-runtime]     event: type=punch_zoom reason=intent_aware_risk_warning_motion_pack
00:32:23 [INFO] [editorial-runtime]     event: type=emphasis_zoom reason=speaker_focus_no_broll
00:32:23 [INFO] [editorial-runtime] ✅ PASS  intent-aware effect selected for risk_warning — intent_aware_effects=1 total_events=2
00:32:23 [INFO] 
00:32:23 [INFO] ════════════════════════════════════════════════════════════
00:32:23 [INFO] [editorial-runtime] RESULTS: 22 PASS / 0 FAIL / 22 TOTAL
00:32:23 [INFO] ════════════════════════════════════════════════════════════
00:32:23 [INFO] [editorial-runtime] ✅ All scenarios PASSED
```

### retention_editing_system

```text
hook_subtitle_only_fails=true
silence_preserve_and_cut=true
retention_gate_strong=true
behind_the_scenes_rejected=true
insurance_content_passes=true
delivery_contract_shortage_logged=true
music_target_db=-21
retention_score=17
```

### premium_runtime_contract

```text
premium_runtime_enabled=true
pipeline_order_contract=true
music_required_if_tracks_found=true
sfx_missing_assets_blocks_strong=true
transition_required_if_planned=true
vfx_required_if_non_weak=true
hook_first3_strong_required=true
filename_contract=true
retention_gate_blocks_plain_outputs=true
behind_the_scenes_rejected=true
requested_3_delivers_3_when_candidates_valid=true
requested_3_shortage_logged_when_only_1_valid=true
music_target_db=-21
```

### py_compile

```text

```
