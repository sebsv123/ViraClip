"""
Audio spectral analysis for viral moment detection.
Uses librosa for tempo, energy peaks, and silence detection.
MIT License - Free alternative to paid competitor features.
"""
import numpy as np
from typing import Dict, List, Tuple, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Lazy import librosa to avoid heavy dependency at module load
def _import_librosa():
    try:
        import librosa
        return librosa
    except ImportError:
        logger.error("librosa not installed. Run: pip install librosa")
        raise


def analyze_audio_virality(audio_path: str) -> Dict:
    """
    Analyze audio for viral potential using spectral features.
    
    Args:
        audio_path: Path to audio file (mp3, wav, etc.)
        
    Returns:
        Dict with tempo, energy peaks, and silence detection data
        
    Features:
        - Tempo analysis: Faster speech = higher engagement
        - RMS energy peaks: High energy = impact moments
        - Silence detection: Dramatic pauses = natural hooks
    """
    librosa = _import_librosa()
    
    logger.info(f"Analyzing audio virality: {audio_path}")
    
    # Load audio
    y, sr = librosa.load(audio_path, sr=None)
    
    # 1. TEMPO ANALYSIS - Faster speech = higher engagement
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    
    # 2. RMS ENERGY - Peaks = impact moments
    rms = librosa.feature.rms(y=y)[0]
    
    # Find energy peaks (above 85th percentile)
    energy_threshold = np.percentile(rms, 85)
    peak_indices = np.where(rms > energy_threshold)[0]
    
    # Convert to timestamps
    hop_length = 512  # librosa default
    energy_peaks_timestamps = (peak_indices * hop_length / sr).tolist()
    
    # 3. SILENCE DETECTION - Dramatic pauses = natural hooks
    # top_db=25: reasonable threshold for speech pauses
    silent_intervals = librosa.effects.split(y, top_db=25)
    
    # Calculate pause durations
    pause_durations = []
    for i in range(len(silent_intervals) - 1):
        pause_start = silent_intervals[i][1]
        pause_end = silent_intervals[i + 1][0]
        pause_duration = (pause_end - pause_start) / sr
        if pause_duration > 0.3:  # Meaningful pause (>300ms)
            pause_durations.append({
                "start": float(pause_start / sr),
                "duration": float(pause_duration),
                "type": "dramatic_pause" if pause_duration > 1.0 else "natural_pause"
            })
    
    # 4. ENVELOPE ANALYSIS - For scene transition detection
    envelope = np.abs(y)
    # Smooth envelope
    window_size = int(sr * 0.1)  # 100ms window
    smoothed = np.convolve(envelope, np.ones(window_size)/window_size, mode='same')
    
    # Find attack points (sudden volume increases)
    diff = np.diff(smoothed)
    attack_threshold = np.std(diff) * 2
    attack_points = np.where(diff > attack_threshold)[0]
    attack_timestamps = (attack_points / sr).tolist()
    
    result = {
        "tempo_bpm": float(tempo),
        "energy_peaks_timestamps": energy_peaks_timestamps[:20],  # Top 20 peaks
        "dramatic_pauses": len([p for p in pause_durations if p["type"] == "dramatic_pause"]),
        "natural_pauses": len([p for p in pause_durations if p["type"] == "natural_pause"]),
        "pause_moments": pause_durations[:10],  # Top 10 meaningful pauses
        "attack_points": attack_timestamps[:15],  # Sudden volume changes
        "average_energy": float(np.mean(rms)),
        "peak_energy": float(np.max(rms)),
        "analysis_duration": len(y) / sr
    }
    
    logger.info(f"Audio analysis complete: {len(energy_peaks_timestamps)} energy peaks, "
                f"{len(pause_durations)} pauses, tempo={tempo:.1f} BPM")
    
    return result


def find_viral_moments_from_audio(
    audio_path: str, 
    min_duration: float = 8.0,
    max_duration: float = 45.0
) -> List[Dict]:
    """
    Identify viral moments based purely on audio analysis.
    
    Returns list of moments with:
        - start/end times
        - confidence score
        - reason (energy_peak, dramatic_pause, tempo_change)
    """
    analysis = analyze_audio_virality(audio_path)
    
    moments = []
    
    # 1. Energy peaks = high impact moments
    for peak_time in analysis["energy_peaks_timestamps"][:10]:
        moments.append({
            "start": max(0, peak_time - 5),  # 5s before peak
            "end": peak_time + 10,  # 10s after peak
            "confidence": 0.85,
            "reason": "energy_peak",
            "audio_feature": "high_energy_moment"
        })
    
    # 2. Dramatic pauses = natural hooks
    for pause in analysis["pause_moments"][:5]:
        if pause["duration"] > 1.0:  # Significant pause
            moments.append({
                "start": max(0, pause["start"] - 3),
                "end": pause["start"] + pause["duration"] + 7,
                "confidence": 0.90,
                "reason": "dramatic_pause",
                "audio_feature": "attention_grabbing_silence"
            })
    
    # 3. Attack points = sudden speech starts
    for attack_time in analysis["attack_points"][:8]:
        moments.append({
            "start": max(0, attack_time - 2),
            "end": attack_time + 13,
            "confidence": 0.75,
            "reason": "sudden_start",
            "audio_feature": "pattern_interrupt"
        })
    
    # Sort by confidence and remove overlaps
    moments.sort(key=lambda x: x["confidence"], reverse=True)
    
    filtered = []
    for m in moments:
        # Check for overlap
        overlap = False
        for f in filtered:
            if not (m["end"] < f["start"] or m["start"] > f["end"]):
                overlap = True
                break
        
        if not overlap:
            # Ensure duration constraints
            duration = m["end"] - m["start"]
            if duration < min_duration:
                m["end"] = m["start"] + min_duration
            elif duration > max_duration:
                m["end"] = m["start"] + max_duration
            
            filtered.append(m)
    
    # Sort by time
    filtered.sort(key=lambda x: x["start"])
    
    logger.info(f"Found {len(filtered)} viral moments from audio analysis")
    return filtered


def extract_audio_from_video(video_path: str, output_audio_path: str) -> bool:
    """Extract audio track from video for analysis."""
    try:
        import subprocess
        
        cmd = [
            "ffmpeg", "-i", video_path,
            "-vn",  # No video
            "-acodec", "libmp3lame",
            "-q:a", "2",  # Good quality
            "-y",  # Overwrite
            output_audio_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Failed to extract audio: {e}")
        return False


# Example usage for testing
if __name__ == "__main__":
    # Test with a sample audio file
    test_audio = "test_audio.mp3"
    if Path(test_audio).exists():
        result = analyze_audio_virality(test_audio)
        print(f"Tempo: {result['tempo_bpm']:.1f} BPM")
        print(f"Energy peaks: {len(result['energy_peaks_timestamps'])}")
        print(f"Dramatic pauses: {result['dramatic_pauses']}")
