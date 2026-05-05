"""
soundagent/audio_analysis/librosa_analyzer.py

Windows-compatible music analysis via librosa.
Fallback for when Essentia is unavailable (Linux/macOS only).
Covers BPM, key, spectral features, and energy profile.
"""

import logging
from pathlib import Path

logger = logging.getLogger("soundagent.audio_analysis.librosa")

_LIBROSA_WARNED = False

# Krumhansl-Schmuckler key profiles (12 pitch classes starting at C)
_MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Minimum Pearson correlation to report a key (below this → inconclusive)
_KEY_CONFIDENCE_MIN = 0.5


def _estimate_key(chroma_mean: "np.ndarray") -> str | None:
    """Correlate mean chroma against Krumhansl-Schmuckler profiles for all 12 keys."""
    import numpy as np

    best_score = -float("inf")
    best_key = None

    for root in range(12):
        for mode, profile in (("major", _MAJOR_PROFILE), ("minor", _MINOR_PROFILE)):
            rotated = [profile[(i - root) % 12] for i in range(12)]
            score = float(np.corrcoef(chroma_mean, rotated)[0, 1])
            if score > best_score:
                best_score = score
                best_key = f"{_NOTE_NAMES[root]} {mode}"

    return best_key if best_score >= _KEY_CONFIDENCE_MIN else None


def analyse(filepath: Path) -> dict | None:
    """
    Run librosa music analysis on filepath.
    Returns dict with keys below, or None if librosa is unavailable or fails.
    Never raises.

    Keys returned:
        bpm: float — estimated tempo in BPM
        bpm_confidence: float — fixed 0.6 (librosa does not provide native confidence)
        key: str | None — estimated key e.g. "C major", "F# minor"
        loudness_rms: float — RMS energy (proxy for perceived loudness)
        dynamic_complexity: float — std dev of RMS across frames
        spectral_centroid_mean: float — brightness proxy (Hz)
        zero_crossing_rate_mean: float — noisiness proxy
        source: str — always "librosa"
    """
    global _LIBROSA_WARNED

    try:
        import librosa
        import numpy as np
    except ImportError:
        if not _LIBROSA_WARNED:
            logger.warning("librosa not installed — music analysis unavailable on this platform")
            _LIBROSA_WARNED = True
        return None

    try:
        path_str = str(filepath)

        # Limit analysis to first 60 s for long files
        duration: float | None = None
        try:
            total = librosa.get_duration(path=path_str)
            if total > 60:
                duration = 60.0
        except Exception:
            pass

        y, sr = librosa.load(path_str, sr=22050, mono=True, duration=duration)

        # BPM
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(np.atleast_1d(tempo)[0])

        # Key via chroma CQT with Krumhansl-Schmuckler profile matching
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        chroma_mean = chroma.mean(axis=1)
        key = _estimate_key(chroma_mean)

        # RMS energy — loudness proxy
        rms_frames = librosa.feature.rms(y=y)[0]
        loudness_rms = float(rms_frames.mean())
        dynamic_complexity = float(rms_frames.std())

        # Spectral centroid — brightness proxy
        centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
        spectral_centroid_mean = float(centroid.mean())

        # Zero crossing rate — noisiness proxy
        zcr = librosa.feature.zero_crossing_rate(y)[0]
        zero_crossing_rate_mean = float(zcr.mean())

        return {
            "bpm": bpm,
            "bpm_confidence": 0.6,
            "key": key,
            "loudness_rms": loudness_rms,
            "dynamic_complexity": dynamic_complexity,
            "spectral_centroid_mean": spectral_centroid_mean,
            "zero_crossing_rate_mean": zero_crossing_rate_mean,
            "source": "librosa",
        }

    except Exception as exc:
        logger.warning(f"librosa analysis failed for {filepath}: {exc}")
        return None
