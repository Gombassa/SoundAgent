import logging
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("soundagent.audio_analysis.audioclip")

_MODEL = None
_WEIGHTS_CHECKED = False
_WEIGHTS_AVAILABLE = False

AUDIOCLIP_PROMPTS = [
    "rain falling on leaves",
    "thunder and lightning storm",
    "wind through trees",
    "ocean waves crashing",
    "fire crackling",
    "footsteps on gravel",
    "footsteps on wood",
    "door creaking",
    "glass breaking",
    "metal impact",
    "explosion",
    "gunshot",
    "crowd noise",
    "traffic and city ambience",
    "bird song",
    "dog barking",
    "engine running",
    "keyboard typing",
    "music with drums",
    "spoken word",
    "silence or low noise floor",
]


def _check_weights(weights_path: str) -> bool:
    global _WEIGHTS_CHECKED, _WEIGHTS_AVAILABLE
    if _WEIGHTS_CHECKED:
        return _WEIGHTS_AVAILABLE
    _WEIGHTS_CHECKED = True
    p = Path(weights_path)
    if not p.exists():
        log.warning(
            f"AudioCLIP weights not found at {weights_path}. "
            "Download AudioCLIP.pt to that path to enable AudioCLIP analysis."
        )
        _WEIGHTS_AVAILABLE = False
    else:
        _WEIGHTS_AVAILABLE = True
    return _WEIGHTS_AVAILABLE


def _get_model(weights_path: str):
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    try:
        import torch
        from AudioCLIP import AudioCLIP
    except ImportError as e:
        raise RuntimeError(f"AudioCLIP/torch not installed: {e}")

    _MODEL = AudioCLIP(pretrained=weights_path)
    _MODEL.eval()
    return _MODEL


def analyse(waveform: np.ndarray, sample_rate: int, audio_cfg: dict) -> list[dict]:
    """
    Score the waveform against a fixed prompt list using AudioCLIP.

    Returns list of {prompt, score} dicts above threshold, up to top 8.
    """
    weights_path = audio_cfg.get("audioclip_weights_path", "models/audioclip/AudioCLIP.pt")
    if not _check_weights(weights_path):
        raise RuntimeError(f"AudioCLIP weights not available at {weights_path}")

    try:
        import torch
        import torchaudio
        import torchaudio.transforms as T
    except ImportError as e:
        raise RuntimeError(f"torch/torchaudio not installed: {e}")

    model = _get_model(weights_path)

    # Resample to 44100 Hz (AudioCLIP's native rate)
    target_sr = 44100
    if sample_rate != target_sr:
        waveform_t = torch.from_numpy(waveform).float().unsqueeze(0)
        resampler = T.Resample(orig_freq=sample_rate, new_freq=target_sr)
        waveform_t = resampler(waveform_t)
    else:
        waveform_t = torch.from_numpy(waveform).float().unsqueeze(0)

    prompts = audio_cfg.get("audioclip_prompts", AUDIOCLIP_PROMPTS)
    threshold = audio_cfg.get("audioclip_threshold", 0.2)

    with torch.no_grad():
        audio_features = model.encode_audio(audio=waveform_t.unsqueeze(0))
        text_tokens = model.tokenize(prompts)
        text_features = model.encode_text(text=text_tokens)

        audio_features = audio_features / audio_features.norm(dim=-1, keepdim=True)
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)
        scores = (audio_features @ text_features.T).squeeze(0)

    scores_np = scores.cpu().numpy()
    ranked = sorted(
        [{"prompt": prompts[i], "score": float(scores_np[i])} for i in range(len(prompts))],
        key=lambda x: x["score"],
        reverse=True,
    )

    return [r for r in ranked[:8] if r["score"] >= threshold]
