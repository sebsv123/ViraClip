"""Fix indentation in fix_clip_renderer.py."""
content = open('fix_clip_renderer.py').read()

old = '''    # PASO 3: Detectar cortes narrativos inteligentes (Capa A)
    from src.core.feature_flags import FEATURE_FLAGS
    if not FEATURE_FLAGS.get("narrative_cut_detection", True):
        logger.info(f"[Clip {clip_index+1}] Step 3: Narrative cuts skipped — disabled by health check")
        segment["narrative_cuts"] = []
    else:
        logger.info(f"[Clip {clip_index+1}] Step 3: Narrative cut detection...")
        cut_engine = NarrativeCutEngine(min_silence_duration=0.5)
        
        # Extraer palabras del segmento (usar el texto)
        words = segment.get("words", [])
        if not words:
        # Crear palabras mock del texto
        words = [{"word": w, "start": 0, "end": 1} for w in segment.get("text", "").split()]
        
        silence_periods = audio_features.get("pause_moments", [])
        silences = [(p["start"], p["start"] + p["duration"]) for p in silence_periods]
        
        cut_points = cut_engine.find_narrative_cuts(
        transcript=segment.get("text", ""),
        words_with_timestamps=words,
        audio_silences=silences,
        audio_energy=audio_features.get("energy_peaks_timestamps", [])
        )
        
        if cut_points:
            logger.info(f"  Found {len(cut_points)} narrative cuts")
            for cp in cut_points[:3]:
                    logger.info(f"    - {cp.timestamp:.1f}s: {cp.reason} ({cp.confidence:.0%})")
        else:
            logger.info(f"  No narrative cuts needed")
        
        segment["narrative_cuts"] = [{
        "timestamp": cp.timestamp,
        "confidence": cp.confidence,
        "reason": cp.reason,
        "transition": cp.suggested_transition
        } for cp in cut_points]'''

new = '''    # PASO 3: Detectar cortes narrativos inteligentes (Capa A)
    from src.core.feature_flags import FEATURE_FLAGS
    if not FEATURE_FLAGS.get("narrative_cut_detection", True):
        logger.info(f"[Clip {clip_index+1}] Step 3: Narrative cuts skipped — disabled by health check")
        segment["narrative_cuts"] = []
    else:
        logger.info(f"[Clip {clip_index+1}] Step 3: Narrative cut detection...")
        cut_engine = NarrativeCutEngine(min_silence_duration=0.5)
        
        # Extraer palabras del segmento (usar el texto)
        words = segment.get("words", [])
        if not words:
            # Crear palabras mock del texto
            words = [{"word": w, "start": 0, "end": 1} for w in segment.get("text", "").split()]
        
        silence_periods = audio_features.get("pause_moments", [])
        silences = [(p["start"], p["start"] + p["duration"]) for p in silence_periods]
        
        cut_points = cut_engine.find_narrative_cuts(
            transcript=segment.get("text", ""),
            words_with_timestamps=words,
            audio_silences=silences,
            audio_energy=audio_features.get("energy_peaks_timestamps", [])
        )
        
        if cut_points:
            logger.info(f"  Found {len(cut_points)} narrative cuts")
            for cp in cut_points[:3]:
                logger.info(f"    - {cp.timestamp:.1f}s: {cp.reason} ({cp.confidence:.0%})")
        else:
            logger.info(f"  No narrative cuts needed")
        
        segment["narrative_cuts"] = [{
            "timestamp": cp.timestamp,
            "confidence": cp.confidence,
            "reason": cp.reason,
            "transition": cp.suggested_transition
        } for cp in cut_points]'''

content = content.replace(old, new)
open('fix_clip_renderer.py', 'w').write(content)
print('Fixed!')
