import logging
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

log = logging.getLogger("soundagent.audio_analysis.preprocessor")


def to_wav(filepath: str, tmp_dir: str, sample_rate: int) -> Path:
    """Convert audio file to mono WAV at the given sample rate using ffmpeg."""
    out_path = Path(tmp_dir) / f"tmp_{sample_rate}hz.wav"
    cmd = [
        "ffmpeg", "-y", "-i", filepath,
        "-ar", str(sample_rate),
        "-ac", "1",
        "-f", "wav",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg conversion failed (exit {result.returncode}): "
            f"{result.stderr.decode(errors='replace')[:500]}"
        )
    return out_path


def load_waveform_float32(wav_path: Path) -> tuple[np.ndarray, int]:
    """Load a WAV file, returning float32 samples in [-1, 1] and sample rate."""
    try:
        samples, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
    except Exception:
        from scipy.io import wavfile
        sr, samples = wavfile.read(str(wav_path))
        if samples.dtype == np.int16:
            samples = samples.astype(np.float32) / 32768.0
        elif samples.dtype == np.int32:
            samples = samples.astype(np.float32) / 2147483648.0
        elif samples.dtype != np.float32:
            samples = samples.astype(np.float32)

    if samples.ndim > 1:
        samples = samples.mean(axis=1)

    return samples, int(sr)


def truncate_waveform(samples: np.ndarray, sample_rate: int, max_seconds: float) -> np.ndarray:
    max_samples = int(max_seconds * sample_rate)
    if len(samples) > max_samples:
        log.warning(
            f"Truncating waveform from {len(samples)/sample_rate:.1f}s "
            f"to {max_seconds:.0f}s for analysis"
        )
        return samples[:max_samples]
    return samples
