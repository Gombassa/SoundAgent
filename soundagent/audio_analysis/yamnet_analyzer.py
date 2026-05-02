import logging
import os
from typing import Optional

import numpy as np

log = logging.getLogger("soundagent.audio_analysis.yamnet")

_MODEL = None
_CLASS_NAMES: Optional[list[str]] = None

_SPEECH_CLASSES = {"Speech", "Narration, monologue", "Conversation"}
_MUSIC_CLASSES = {"Music", "Musical instrument", "Singing"}


def _get_model():
    global _MODEL, _CLASS_NAMES
    if _MODEL is not None:
        return _MODEL, _CLASS_NAMES

    try:
        import tensorflow as tf
        import tensorflow_hub as hub
        import csv
        import io
        import urllib.request
    except ImportError as e:
        raise RuntimeError(f"TensorFlow not installed: {e}")

    cache_dir = os.environ.get("TFHUB_CACHE_DIR", os.path.join(os.path.expanduser("~"), ".cache", "tfhub"))
    os.environ["TFHUB_CACHE_DIR"] = cache_dir

    _MODEL = hub.load("https://tfhub.dev/google/yamnet/1")

    # Load class map from the model
    class_map_path = _MODEL.class_map_path().numpy().decode()
    with urllib.request.urlopen(class_map_path) as f:
        reader = csv.DictReader(io.TextIOWrapper(f))
        _CLASS_NAMES = [row["display_name"] for row in reader]

    return _MODEL, _CLASS_NAMES


def analyse(waveform: np.ndarray, sample_rate: int, audio_cfg: dict) -> dict:
    """
    Run YAMNet on a waveform and return content-type classification.

    Returns dict with: classes, embedding, content_type, speech_score.
    """
    if sample_rate != 16000:
        raise ValueError(f"YAMNet requires 16kHz audio; got {sample_rate}Hz")

    model, class_names = _get_model()

    import tensorflow as tf
    waveform_tf = tf.constant(waveform, dtype=tf.float32)
    scores, embeddings, _ = model(waveform_tf)

    scores_np = scores.numpy()
    mean_scores = scores_np.mean(axis=0)

    top_n = 10
    top_indices = mean_scores.argsort()[-top_n:][::-1]
    top_classes = [class_names[i] for i in top_indices]

    speech_threshold = audio_cfg.get("speech_threshold", 0.4)
    music_threshold = audio_cfg.get("music_threshold", 0.3)

    speech_score = sum(mean_scores[i] for i, c in enumerate(class_names) if c in _SPEECH_CLASSES)
    music_score = sum(mean_scores[i] for i, c in enumerate(class_names) if c in _MUSIC_CLASSES)

    if speech_score >= speech_threshold:
        content_type = "speech"
    elif music_score >= music_threshold:
        content_type = "music"
    else:
        content_type = "sfx_or_field"

    # Average embedding across frames for a single vector
    avg_embedding = embeddings.numpy().mean(axis=0).tolist()

    return {
        "classes": top_classes,
        "embedding": avg_embedding,
        "content_type": content_type,
        "speech_score": float(speech_score),
    }
