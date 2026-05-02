import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AudioMetadata:
    duration_s: float
    sample_rate: int
    bit_depth: int | None
    channels: int
    format: str
    codec: str
    file_size: int


def extract(path: Path) -> AudioMetadata:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams", "-show_format",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        raise RuntimeError("ffprobe not found — ensure FFmpeg is installed and on PATH")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffprobe failed for {path}: {e.stderr.strip()}")

    data = json.loads(result.stdout)
    audio = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
        None,
    )
    if audio is None:
        raise ValueError(f"No audio stream in {path}")

    fmt = data.get("format", {})
    raw_bits = audio.get("bits_per_sample") or audio.get("bits_per_raw_sample")

    return AudioMetadata(
        duration_s=float(fmt.get("duration", 0)),
        sample_rate=int(audio.get("sample_rate", 0)),
        bit_depth=int(raw_bits) if raw_bits else None,
        channels=int(audio.get("channels", 0)),
        format=fmt.get("format_name", ""),
        codec=audio.get("codec_name", ""),
        file_size=int(fmt.get("size", 0)),
    )
