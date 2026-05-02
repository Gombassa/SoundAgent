import logging
from typing import Optional

log = logging.getLogger("soundagent.audio_analysis.essentia")


def analyse(filepath: str) -> dict:
    """
    Extract music descriptors from an audio file using Essentia's MusicExtractor.

    Returns dict with: bpm, bpm_confidence, key, loudness, mood (optional), genre (optional).
    """
    try:
        import essentia.standard as es
    except ImportError as e:
        raise RuntimeError(f"essentia not installed: {e}")

    extractor = es.MusicExtractor(
        lowlevelSilenceRate60dBThreshold=-60,
        lowlevelFrameSize=2048,
        lowlevelHopSize=1024,
    )
    features, _ = extractor(filepath)

    bpm = float(features["rhythm.bpm"])
    bpm_confidence = float(features["rhythm.bpm_confidence"]) if "rhythm.bpm_confidence" in features.descriptorNames() else None

    key_key = features["tonal.key_key"]
    key_scale = features["tonal.key_scale"]
    key = f"{key_key} {key_scale}" if key_key and key_scale else None

    loudness: Optional[float] = None
    try:
        loudness = float(features["lowlevel.loudness_ebu128.integrated"])
    except Exception:
        try:
            loudness = float(features["lowlevel.average_loudness"])
        except Exception:
            pass

    mood: Optional[dict] = None
    try:
        mood = {
            "happy": float(features["highlevel.mood_happy.all.happy"]),
            "sad": float(features["highlevel.mood_sad.all.sad"]),
            "relaxed": float(features["highlevel.mood_relaxed.all.relaxed"]),
            "aggressive": float(features["highlevel.mood_aggressive.all.aggressive"]),
        }
    except KeyError:
        pass

    genre: Optional[dict] = None
    try:
        genre = {
            "electronic": float(features["highlevel.genre_electronic.all.electronic"]),
            "rock": float(features["highlevel.genre_rosamerica.all.roc"]),
            "classical": float(features["highlevel.genre_rosamerica.all.cla"]),
        }
    except KeyError:
        pass

    return {
        "bpm": bpm,
        "bpm_confidence": bpm_confidence,
        "key": key,
        "loudness": loudness,
        "mood": mood,
        "genre": genre,
    }
