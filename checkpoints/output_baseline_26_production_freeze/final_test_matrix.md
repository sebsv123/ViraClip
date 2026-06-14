# OUTPUT-BASELINE-26 Final Test Matrix

No new smokes or tasks were launched. Only existing suites/harnesses were executed.

| Area | Command / Harness | Result | Artifact |
| --- | --- | --- | --- |
| py_compile | Production service files + existing harnesses | PASS | `py_compile.txt` |
| TIMELINE-25 | `checkpoints/output_timeline_25_canonical_keep_segments/test_timeline_25.py` | 12 passed, 0 failed | `test_timeline_25.txt` |
| TIMELINE-24 | `checkpoints/output_timeline_24_post_silence_remap/test_timeline_24.py` | 13 passed, 0 failed | `test_timeline_24.txt` |
| TIMELINE-23 | `checkpoints/output_timeline_23_final_duration_reconciliation/test_timeline_23.py` | 11 passed, 0 failed | `test_timeline_23.txt` |
| SFX-19 | `checkpoints/output_sfx_19_payoff_risk/test_sfx_19_payoff_risk.py` | 16 passed, 0 failed | `test_sfx_19.txt` |
| VISUALS-17 | `checkpoints/output_visuals_17_semantic_icon_mapping/test_visuals_17_mapping.py` | 11 passed, 0 failed | `test_visuals_17.txt` |
| VISUALS-16 | `checkpoints/output_visuals_16_icon_object_polish/test_visuals_16_icon.py` | 11 passed, 0 failed | `test_visuals_16.txt` |
| BROLL-14 | `checkpoints/output_broll_14_asset_intake_travel_student/test_broll_14_intake.py` | 11 passed, 0 failed | `test_broll_14.txt` |
| BROLL-13 | `checkpoints/output_broll_13_visual_polish/test_broll_13.py` | 10 passed, 0 failed | `test_broll_13.txt` |
| NARRATIVE-9 | `checkpoints/output_narrative_9_closure_planner/test_narrative_9.py` in backend container | 9 passed, 0 failed | `test_narrative_9.txt` |
| Caption contract | `checkpoints/output_selection_5b_post_trim_caption_contract/contract_tests.py` in backend container | ALL CONTRACT TESTS PASS | `test_caption_contract_5b.txt` |

## Notes

- NARRATIVE-9 and caption contract were executed inside `viraclip-backend` because the host Python environment does not include backend runtime dependencies.
- BROLL-13 emits expected corrupt-asset fallback diagnostics; harness result is PASS.
- TIMELINE-23 emits an expected truncation-gate diagnostic for the regression fixture; harness result is PASS.
