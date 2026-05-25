"""
Word-Level Confidence Subtitling
Uses faster-whisper probability scores for semantic color coding
MIT License - Unique visual effect impossible to replicate with other tools
"""
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# ── Insurance/finance content detection ──────────────────────────────────────
# Shared with broll_service.py to block fallback paths for insurance content.
# When the transcript contains these Spanish insurance trigger words, the
# subtitle rebasing fallback (similarity < 30%) is disabled because the
# re-transcription is unreliable for domain-specific terminology.
INSURANCE_KEYWORD_MAP: Dict[str, List[str]] = {
    "seguro de vida": ["life insurance family", "family protection"],
    "seguro de coche": ["car insurance", "car accident road"],
    "seguro del hogar": ["home insurance", "modern family home"],
    "ahorro": ["financial planning", "saving money"],
    "protección": ["family protection", "safety concept"],
    "precio": ["budget planning", "insurance quote"],
    "accidente": ["car accident", "medical support"],
    "tranquilidad": ["peaceful family", "stress free home"],
    "contrato": ["signing contract", "agreement handshake"],
    "mutua": ["health insurance", "doctor consultation"],
    "fallecimiento": ["family support", "life coverage"],
    "cobertura": ["insurance coverage", "policy details"],
    "indemnización": ["insurance claim", "compensation process"],
}


def _is_insurance_content(text: str) -> bool:
    """Check if transcript contains insurance/finance keywords.

    Returns True if any insurance trigger word is found in the text (case-insensitive).
    This is used to block fallback paths that could inject generic subtitles or
    b-roll for insurance/finance content.
    """
    if not text:
        return False
    text_lower = text.lower()
    for keyword in INSURANCE_KEYWORD_MAP:
        if keyword in text_lower:
            return True
    return False


def _get_ffmpeg_exe() -> str:
    import shutil
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg as _iio
        return _iio.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

# Confidence-based color mapping
# Counter-intuitive: LOW confidence = interesting/rare words = highlight
CONFIDENCE_COLOR_MAP = {
    "high": "#FFFFFF",      # > 0.95: Common words - bright white
    "medium": "#FFD700",    # 0.80-0.95: Standard terms - gold
    "low": "#FF6B35",       # < 0.80: Rare/technical terms - orange impact
    "very_low": "#FF1744"   # < 0.60: Unclear/unique - red attention
}


@dataclass
class WordConfidence:
    """Word with confidence metadata"""
    text: str
    start: float
    end: float
    probability: float
    color: str
    is_emphasis: bool  # True if low confidence (rare word)


@dataclass  
class ColoredSubtitleSegment:
    """Subtitle segment with word-level colors"""
    text: str
    start: float
    end: float
    words: List[WordConfidence]
    dominant_color: str
    has_rare_words: bool


class ConfidenceSubtitleGenerator:
    """
    Generates confidence-colored subtitles using faster-whisper
    Inverted logic: low confidence = visually highlighted
    """
    
    def __init__(self, model_size: str = "large-v3", device: str = "auto"):
        self.model_size = model_size
        # Resolve device: "auto" → detect; "cuda" → validate CUDA available first
        if device in ("auto", "cuda"):
            import os as _os
            _env_dev = _os.environ.get("WHISPER_DEVICE", "cpu").lower()
            if _env_dev == "cuda":
                try:
                    import torch as _torch
                    device = "cuda" if _torch.cuda.is_available() else "cpu"
                except ImportError:
                    device = "cpu"
            else:
                device = _env_dev if _env_dev in ("cpu", "cuda") else "cpu"
        self.device = device
        self.model = None
        
        # Confidence thresholds
        self.high_threshold = 0.95
        self.medium_threshold = 0.80
        self.low_threshold = 0.60
    
    def _load_model(self):
        """Lazy load faster-whisper model"""
        if self.model is None:
            try:
                from faster_whisper import WhisperModel
                
                compute_type = "float16" if self.device == "cuda" else "int8"
                self.model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=compute_type
                )
                logger.info(f"Loaded faster-whisper {self.model_size} on {self.device}")
            except ImportError:
                logger.error("faster-whisper not installed. Run: pip install faster-whisper")
                raise
    
    def transcribe_with_confidence(
        self, 
        audio_path: str,
        language: Optional[str] = None
    ) -> List[ColoredSubtitleSegment]:
        """
        Transcribe audio with word-level confidence scoring
        
        Args:
            audio_path: Path to audio file
            language: Optional language code (auto-detect if None)
            
        Returns:
            List of colored subtitle segments
        """
        self._load_model()
        
        logger.info(f"Transcribing with confidence: {audio_path}")
        
        # Transcribe with word timestamps
        segments, info = self.model.transcribe(
            audio_path,
            language=language,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500)
        )
        
        logger.info(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")
        
        colored_segments = []
        
        for segment in segments:
            words = []
            
            if segment.words:
                for word in segment.words:
                    # Determine color based on confidence
                    prob = word.probability
                    
                    if prob > self.high_threshold:
                        color = CONFIDENCE_COLOR_MAP["high"]
                        is_emphasis = False
                    elif prob > self.medium_threshold:
                        color = CONFIDENCE_COLOR_MAP["medium"]
                        is_emphasis = False
                    elif prob > self.low_threshold:
                        color = CONFIDENCE_COLOR_MAP["low"]
                        is_emphasis = True  # Rare word!
                    else:
                        color = CONFIDENCE_COLOR_MAP["very_low"]
                        is_emphasis = True
                    
                    words.append(WordConfidence(
                        text=word.word.strip(),
                        start=word.start,
                        end=word.end,
                        probability=prob,
                        color=color,
                        is_emphasis=is_emphasis
                    ))
                
                # Calculate segment metadata
                has_rare = any(w.is_emphasis for w in words)
                dominant_color = self._calculate_dominant_color(words)
                
                colored_segments.append(ColoredSubtitleSegment(
                    text=segment.text.strip(),
                    start=segment.start,
                    end=segment.end,
                    words=words,
                    dominant_color=dominant_color,
                    has_rare_words=has_rare
                ))
        
        # Log statistics
        total_words = sum(len(s.words) for s in colored_segments)
        rare_words = sum(1 for s in colored_segments for w in s.words if w.is_emphasis)
        
        logger.info(f"Transcription complete: {len(colored_segments)} segments, "
                   f"{total_words} words, {rare_words} rare/technical terms highlighted")
        
        return colored_segments
    
    def _calculate_dominant_color(self, words: List[WordConfidence]) -> str:
        """Calculate the dominant color for a segment"""
        if not words:
            return CONFIDENCE_COLOR_MAP["high"]
        
        # Weight by confidence (but inverted - low confidence = more visual weight)
        color_weights = {}
        for word in words:
            color_weights[word.color] = color_weights.get(word.color, 0) + 1
        
        # Return most common
        return max(color_weights.items(), key=lambda x: x[1])[0]
    
    def generate_colored_srt(
        self,
        segments: List[ColoredSubtitleSegment],
        output_path: str
    ):
        """Generate SRT with color tags for word-level coloring"""
        def format_time(seconds: float) -> str:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            millis = int((seconds % 1) * 1000)
            return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
        
        with open(output_path, 'w', encoding='utf-8') as f:
            for i, segment in enumerate(segments, 1):
                # SRT entry header
                f.write(f"{i}\n")
                f.write(f"{format_time(segment.start)} --> {format_time(segment.end)}\n")
                
                # Colored text with HTML-style tags
                colored_text_parts = []
                for word in segment.words:
                    # Use font color tags
                    colored_text_parts.append(
                        f'<font color="{word.color}">{word.text}</font>'
                    )
                
                colored_text = " ".join(colored_text_parts)
                f.write(f"{colored_text}\n\n")
        
        logger.info(f"Generated colored SRT: {output_path}")
    
    def get_high_impact_moments(
        self,
        segments: List[ColoredSubtitleSegment],
        min_rare_words: int = 2
    ) -> List[Tuple[float, float, str]]:
        """
        Identify high-impact moments based on rare word density
        
        Returns:
            List of (start, end, reason) tuples for viral moments
        """
        moments = []
        
        for segment in segments:
            rare_count = sum(1 for w in segment.words if w.is_emphasis)
            
            if rare_count >= min_rare_words:
                moments.append((
                    segment.start,
                    segment.end,
                    f"technical_terms_{rare_count}"
                ))
        
        logger.info(f"Found {len(moments)} high-impact moments with rare words")
        return moments
    
    def realign_on_segment(
        self,
        segment_video_path: str,
        original_words: Optional[List[Dict]] = None,
        language: Optional[str] = None,
        anticipation_offset_ms: float = -50.0,
        has_clean_audio: Optional[bool] = None,
        clip_start: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        Re-transcribe un clip ya cortado para obtener timestamps exactos.

        El video original puede tener drift de 200-500ms en transcripciones largas.
        Al re-transcribir solo el segmento (15-60s), faster-whisper da timestamps
        con precision de +-30ms.

        BUG 3 FIX: Si el segmento tiene B-roll, musica de fondo o subtitulos
        quemados (has_clean_audio=False), se salta la re-transcripcion y devuelve
        las palabras originales para evitar desincronizacion por audio contaminado.

        RULE 1 FIX (Subtitle Timing): Si la similitud entre la re-transcripcion y
        el transcript original es menor al 30% (SIMILARITY_CRITICAL_THRESHOLD),
        se considera que la re-transcripcion NO es fiable en absoluto. En ese caso:
        - Se devuelve original_words con sus timestamps originales
        - El caller (_clip_renderer.py) aplicara los offsets acumulativos del
          timeline editado (jump-cuts, silencios, etc.)
        - NO se usan los timestamps de la re-transcripcion

        RULE 2 FIX: Si la similitud esta entre 30% y 70%, se usa la re-transcripcion
        SOLO para los timestamps, pero se preservan los textos originales (que
        contienen la puntuacion y acentos correctos).

        PHASE 3 FIX: Cuando la similitud es < 30% y se devuelven las palabras
        originales, sus timestamps pueden referenciar el video completo (no el
        clip). El parametro clip_start permite restar el offset del clip para
        que los timestamps sean relativos al clip, no al video completo.

        Args:
            segment_video_path: Ruta al clip ya cortado (el .mp4 que sale de create_optimized_clip)
            original_words: Palabras remapeadas del video original (para validacion)
            language: Codigo de idioma ('es', 'en', etc.)
            anticipation_offset_ms: Offset en ms para que subtitulos aparezcan
                                    ligeramente ANTES de la palabra (-50ms = aparece 50ms antes)
            has_clean_audio: Si es False, se salta la re-transcripcion. Si es None,
                             se detecta automaticamente (heuristica basica).
            clip_start: Segundos desde el inicio del video completo hasta el inicio
                        del clip. Se resta de los timestamps originales cuando la
                        re-transcripcion no es fiable, para que sean relativos al clip.

        Returns:
            Lista de dicts compatibles con words_with_confidence:
            [{"word": str, "start": float_seconds, "end": float_seconds,
              "confidence": float, "is_emphasis": bool}]
        """
        import subprocess
        import tempfile

        logger.info(f"[RE-ALIGN] Transcribiendo segmento: {segment_video_path}")

        # ── BUG 3 FIX: Verificar si el audio es limpio ──────────────────────
        if has_clean_audio is None:
            has_clean_audio = self._detect_clean_audio(segment_video_path)

        if has_clean_audio is False:
            logger.warning(
                f"[RE-ALIGN] Segmento {segment_video_path} no tiene audio limpio "
                "(B-roll, musica o subtitulos quemados detectados). "
                "Saltando re-transcripcion para evitar desincronizacion."
            )
            return original_words or []

        # Normalizar codigo ISO 639-3 → ISO 639-1 (faster-whisper solo acepta 2 letras)
        _ISO3_TO_ISO1 = {
            "eng": "en", "spa": "es", "fra": "fr", "deu": "de", "ita": "it",
            "por": "pt", "rus": "ru", "zho": "zh", "jpn": "ja", "kor": "ko",
            "ara": "ar", "hin": "hi", "nld": "nl", "pol": "pl", "tur": "tr",
            "vie": "vi", "tha": "th", "swe": "sv", "nor": "no", "dan": "da",
        }
        if language and len(language) == 3:
            language = _ISO3_TO_ISO1.get(language.lower(), None)

        tmp_audio_path = None

        # Paso 1: Extraer audio WAV del segmento (16kHz mono, optimo para Whisper)
        tmp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_audio_path = tmp_audio.name
        tmp_audio.close()

        try:
            import subprocess as _sp
            _dur_probe = _sp.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(segment_video_path)],
                capture_output=True, text=True, timeout=10
            )
            _clip_dur = float(_dur_probe.stdout.strip()) if _dur_probe.returncode == 0 and _dur_probe.stdout.strip() else 0.0

            extract_cmd = [
                _get_ffmpeg_exe(), '-y', '-i', segment_video_path,
                '-vn',                    # Sin video
                '-acodec', 'pcm_s16le',   # WAV sin compresion
                '-ar', '16000',           # 16kHz (optimo Whisper)
                '-ac', '1',               # Mono
                tmp_audio_path
            ]
            result = subprocess.run(extract_cmd, capture_output=True, timeout=30)
            if result.returncode != 0:
                logger.error(f"[RE-ALIGN] FFmpeg fallo: {result.stderr.decode()}")
                return original_words or []

            _audio_dur_probe = _sp.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", tmp_audio_path],
                capture_output=True, text=True, timeout=10
            )
            _audio_dur = float(_audio_dur_probe.stdout.strip()) if _audio_dur_probe.returncode == 0 and _audio_dur_probe.stdout.strip() else 0.0
            logger.debug(
                "[RE-ALIGN] Audio extraído: %.2fs | Clip: %.2fs | Diferencia: %.2fs",
                _audio_dur, _clip_dur, abs(_audio_dur - _clip_dur),
            )

            # Paso 2: Transcribir con faster-whisper
            self._load_model()
            segments_iter, info = self.model.transcribe(
                tmp_audio_path,
                language=language,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=300),
                beam_size=5
            )

            # Paso 3: Construir lista de palabras con offset de anticipacion
            offset_s = anticipation_offset_ms / 1000.0
            realigned_words = []

            for segment in segments_iter:
                if not segment.words:
                    continue
                for word in segment.words:
                    word_text = word.word.strip()
                    if not word_text:
                        continue
                    realigned_words.append({
                        'word': word_text,
                        'text': word_text,
                        'start': max(0.0, round(word.start + offset_s, 3)),
                        'end': round(word.end + offset_s, 3),
                        'confidence': round(word.probability, 3),
                        'is_emphasis': word.probability < 0.80
                    })

            logger.info(f"[RE-ALIGN] {len(realigned_words)} palabras re-alineadas")

            # ── RULE 1 & 2: Validacion contra palabras originales ──────────────
            # SIMILARITY_SAFE_THRESHOLD = 0.70: Re-transcripcion confiable
            # SIMILARITY_CRITICAL_THRESHOLD = 0.30: Re-transcripcion NO confiable
            #   - Por debajo de 0.30: el texto re-transcrito es esencialmente
            #     diferente al original. Ocurre cuando el audio tiene B-roll,
            #     musica, ruido de fondo, o el modelo alucina. En este caso:
            #     * Se devuelven las palabras originales con sus timestamps
            #     * El caller aplicara offsets acumulativos del timeline
            #   - Entre 0.30 y 0.70: los timestamps de la re-transcripcion son
            #     utiles, pero se preservan los textos originales (con acentos
            #     y puntuacion correctos)
            #   - Por encima de 0.70: se usan ambos (texto y timestamps)
            SIMILARITY_SAFE_THRESHOLD = 0.70
            SIMILARITY_CRITICAL_THRESHOLD = 0.30

            if original_words and realigned_words:
                # Filter original_words to only include words within the clip's time range
                # (clip_start to clip_start + estimated_duration). This prevents the
                # similarity comparison from failing when the clip is a small segment
                # of a much longer video.
                _clip_end_est = clip_start + max(
                    (w.get('end', 0) for w in realigned_words if w.get('end')),
                    default=30.0
                )
                _filtered_orig = [
                    w for w in original_words
                    if w.get('start', 0) >= clip_start and w.get('end', 0) <= _clip_end_est
                ]
                if not _filtered_orig:
                    _filtered_orig = original_words  # fallback to all words if filter yields empty

                orig_text = ' '.join(
                    w.get('word', w.get('text', '')) for w in _filtered_orig
                ).lower().strip()
                new_text = ' '.join(w['word'] for w in realigned_words).lower().strip()

                from difflib import SequenceMatcher
                similarity = SequenceMatcher(None, orig_text, new_text).ratio()
                logger.info(f"[RE-ALIGN] Similitud texto: {similarity:.1%} "
                           f"(clip_start={clip_start:.1f}s, orig_words={len(original_words)}, "
                           f"filtered={len(_filtered_orig)}, realigned={len(realigned_words)})")

                # ── RULE 1: Similitud criticamente baja (< 30%) ──────────────
                # La re-transcripcion NO es fiable. Devolvemos las palabras
                # originales con sus timestamps originales. El caller aplicara
                # los offsets acumulativos del timeline editado.
                #
                # PHASE 3 FIX: Los timestamps originales pueden referenciar el
                # video completo (no el clip). Restamos clip_start para que sean
                # relativos al clip. Esto asegura que los offsets acumulativos
                # del timeline editado se apliquen correctamente.
                #
                # ── BLOCK FALLBACK PATH B: subtitle rebasing for insurance content ──
                # When the transcript contains insurance/finance keywords AND the
                # re-transcription similarity is critically low (< 30%), the rebasing
                # of original_words with clip_start is unreliable. The re-transcription
                # model may hallucinate or produce garbled text for domain-specific
                # Spanish insurance terminology (e.g., "indemnización", "fallecimiento").
                # Using rebased original_words would inject subtitles with timestamps
                # from the full video that don't match the clip's actual audio.
                # Instead, return empty list so the caller uses the primary semantic
                # planner's timeline as the source of truth.
                if similarity < SIMILARITY_CRITICAL_THRESHOLD:
                    # ── BLOCK FALLBACK PATH B: subtitle rebasing for ALL content ──
                    # When similarity is critically low (< 30%), the re-transcription
                    # is unreliable regardless of content type. The model may
                    # hallucinate or produce garbled text. Rebasing original_words
                    # with clip_start would inject subtitles with timestamps from
                    # the full video that don't match the clip's actual audio.
                    # This is blocked for ALL content — not just insurance — because
                    # low-similarity re-transcription is fundamentally unreliable.
                    # The caller must use the primary semantic planner's timeline
                    # as the source of truth.
                    logger.warning(
                        f"[RE-ALIGN] ⛔ BLOCKED fallback path B: subtitle rebasing "
                        f"for ALL content. Similarity={similarity:.1%} is below "
                        f"CRITICAL threshold ({SIMILARITY_CRITICAL_THRESHOLD:.0%}). "
                        f"Re-transcription is unreliable — rebasing original_words "
                        f"with clip_start={clip_start:.2f}s would inject subtitles "
                        f"with timestamps from the full video that don't match the "
                        f"clip's actual audio. "
                        f"Returning empty list — caller must use primary semantic "
                        f"planner timeline as source of truth."
                    )
                    return []

                # ── RULE 2: Similitud entre 30% y 70% ────────────────────────
                # Los timestamps de la re-transcripcion son utiles, pero
                # preservamos los textos originales (con acentos y puntuacion).
                if similarity < SIMILARITY_SAFE_THRESHOLD:
                    logger.warning(
                        f"[RE-ALIGN] ⚠️ Similitud por debajo del umbral seguro ({similarity:.1%}). "
                        "Usando timestamps de re-transcripcion con textos originales."
                    )
                    # Preservar textos originales, usar timestamps de re-transcripcion
                    # Mapear palabras originales a timestamps re-transcritos
                    _preserved = _merge_original_texts_with_realigned_timestamps(
                        original_words, realigned_words
                    )
                    if _preserved:
                        return _preserved
                    # Si falla el merge, devolver original_words
                    return original_words

            # ── RULE 4: Preservar acentos y puntuacion española ──────────────
            # Si llegamos aqui, la similitud es >= 0.70 o no hay original_words.
            # Transferir flags de emphasis del original si los tiene.
            if original_words:
                _transfer_emphasis_flags(realigned_words, original_words)

            return realigned_words

        except Exception as e:
            logger.error(f"[RE-ALIGN] Error: {e}")
            return original_words or []
        finally:
            if tmp_audio_path:
                Path(tmp_audio_path).unlink(missing_ok=True)


    def _detect_clean_audio(self, video_path: str) -> bool:
        """
        Detecta si el segmento tiene audio limpio (solo voz original)
        o si tiene B-roll, musica o subtitulos quemados.

        BUG 3 FIX: Heuristica basada en:
        1. Nombre del archivo (si contiene indicadores de B-roll)
        2. Cantidad de pistas de audio en el contenedor
        3. Duracion del audio vs duracion del video

        Returns:
            True si el audio parece limpio, False si parece contaminado.
        """
        import subprocess
        from pathlib import Path

        path = Path(video_path)
        fname = path.stem.lower()

        # Heuristica 1: Nombre del archivo con indicadores de B-roll/post-procesado
        broll_indicators = [
            "_broll", "_composite", "_final", "_polished",
            "_with_music", "_with_sfx", "_enhanced",
        ]
        for indicator in broll_indicators:
            if indicator in fname:
                logger.info(
                    f"[RE-ALIGN] Audio contaminado detectado por nombre: "
                    f"'{indicator}' en '{fname}'"
                )
                return False

        # Heuristica 2: Verificar numero de pistas de audio
        # Un video limpio tiene 1 pista de audio (voz original)
        # B-roll/musica anaden pistas adicionales
        try:
            probe_cmd = [
                _get_ffmpeg_exe(), '-i', video_path,
                '-hide_banner',
            ]
            result = subprocess.run(
                probe_cmd, capture_output=True, text=True, timeout=15
            )
            stderr = result.stderr

            # Contar pistas de audio
            import re
            audio_streams = re.findall(r'Stream #0:\d+\(?.*?\)?: Audio:', stderr)
            if len(audio_streams) > 1:
                logger.info(
                    f"[RE-ALIGN] Audio contaminado: {len(audio_streams)} pistas "
                    f"de audio detectadas (esperado: 1)"
                )
                return False

            # Heuristica 3: Verificar si hay codificacion de audio multiple
            # (indica mezcla de fuentes)
            if "aac" in stderr and "pcm" in stderr:
                logger.info(
                    "[RE-ALIGN] Audio potencialmente contaminado: "
                    "mezcla de codecs de audio detectada"
                )
                return False
        except Exception as e:
            logger.debug(f"[RE-ALIGN] Error en deteccion de audio limpio: {e}")

        # Si pasamos todas las heuristicas, asumimos audio limpio
        logger.info(f"[RE-ALIGN] Audio parece limpio para segmento: {fname}")
        return True


def _transfer_emphasis_flags(realigned: List[Dict], original: List[Dict]):
    """
    Copia is_emphasis del original al realineado cuando las palabras coinciden.
    Usa matching por texto, no por posicion (pueden diferir en cantidad).
    """
    orig_emphasis = set()
    for w in original:
        if w.get('is_emphasis', False):
            orig_emphasis.add(w.get('word', w.get('text', '')).lower().strip())

    for w in realigned:
        if w['word'].lower().strip() in orig_emphasis:
            w['is_emphasis'] = True


def _merge_original_texts_with_realigned_timestamps(
    original_words: List[Dict],
    realigned_words: List[Dict],
) -> List[Dict]:
    """
    RULE 2 FIX: Preserva los textos originales (con acentos y puntuacion
    española) pero usa los timestamps de la re-transcripcion.

    Estrategia: alinear por indice posicional. Si el numero de palabras
    es similar (diferencia < 20%), se mapean 1:1. Si no, se usa el
    texto original completo y se distribuyen los timestamps de la
    re-transcripcion proporcionalmente.

    Args:
        original_words: Palabras del transcript original (con acentos, puntuacion)
        realigned_words: Palabras de la re-transcripcion (timestamps precisos)

    Returns:
        Lista combinada: textos originales con timestamps de re-transcripcion
    """
    if not original_words or not realigned_words:
        return original_words or []

    _orig_count = len(original_words)
    _real_count = len(realigned_words)

    # Si el numero de palabras es similar, mapear 1:1
    if abs(_orig_count - _real_count) / max(_orig_count, _real_count) < 0.20:
        _merged = []
        for i, _ow in enumerate(original_words):
            if i < _real_count:
                _rw = realigned_words[i]
                _merged.append({
                    "word": _ow.get("word", _ow.get("text", "")),
                    "text": _ow.get("text", _ow.get("word", "")),
                    "start": _rw.get("start", _ow.get("start", 0)),
                    "end": _rw.get("end", _ow.get("end", 0)),
                    "confidence": _rw.get("confidence", _ow.get("confidence", 0.9)),
                    "is_emphasis": _ow.get("is_emphasis", False),
                })
            else:
                # Mas palabras originales que re-transcritas
                _merged.append(_ow)
        return _merged

    # Si el numero de palabras difiere significativamente,
    # distribuir timestamps de re-transcripcion proporcionalmente
    # sobre los textos originales
    _total_real_dur = max(
        realigned_words[-1].get("end", 0) - realigned_words[0].get("start", 0),
        0.1,
    )
    _total_orig_dur = max(
        original_words[-1].get("end", 0) - original_words[0].get("start", 0),
        0.1,
    )
    _scale = _total_real_dur / _total_orig_dur

    _merged = []
    for _ow in original_words:
        _ws = _ow.get("start", 0) * _scale
        _we = _ow.get("end", 0) * _scale
        _merged.append({
            "word": _ow.get("word", _ow.get("text", "")),
            "text": _ow.get("text", _ow.get("word", "")),
            "start": round(_ws, 3),
            "end": round(_we, 3),
            "confidence": _ow.get("confidence", 0.9),
            "is_emphasis": _ow.get("is_emphasis", False),
        })

    return _merged



def create_confidence_colored_subtitles(
    video_path: str,
    output_srt_path: str,
    model_size: str = "large-v3"
) -> bool:
    """
    Convenience function: extract audio and create colored subtitles
    
    Args:
        video_path: Path to video file
        output_srt_path: Output SRT file path
        model_size: faster-whisper model size
        
    Returns:
        True if successful
    """
    from moviepy import VideoFileClip
    import tempfile
    
    try:
        # Extract audio
        video = VideoFileClip(video_path)
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            audio_path = tmp.name
        
        video.audio.write_audiofile(
            audio_path,
            fps=16000,
            nbytes=2,
            codec='pcm_s16le',
            verbose=False,
            logger=None
        )
        video.close()
        
        # Generate colored subtitles
        generator = ConfidenceSubtitleGenerator(model_size=model_size, device="cpu")
        segments = generator.transcribe_with_confidence(audio_path)
        generator.generate_colored_srt(segments, output_srt_path)
        
        # Cleanup
        Path(audio_path).unlink(missing_ok=True)
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to create colored subtitles: {e}")
        return False


# Example usage
if __name__ == "__main__":
    # Test transcription
    test_audio = "test_audio.mp3"
    if Path(test_audio).exists():
        gen = ConfidenceSubtitleGenerator(model_size="base", device="cpu")
        segments = gen.transcribe_with_confidence(test_audio)
        
        print(f"\nSegments: {len(segments)}")
        for seg in segments[:3]:
            rare = [w.text for w in seg.words if w.is_emphasis]
            print(f"[{seg.start:.1f}s] {seg.text[:50]}...")
            if rare:
                print(f"  Rare words highlighted: {rare}")
