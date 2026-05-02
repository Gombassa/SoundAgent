from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AnalysisResult:
    file_hash: str
    fallback_only: bool

    # YAMNet
    yamnet_classes: list[str] = field(default_factory=list)
    yamnet_embedding: Optional[list[float]] = None
    content_type: str = "sfx_or_field"   # "speech" | "music" | "sfx_or_field"
    speech_score: float = 0.0

    # AudioCLIP
    audioclip_matches: list[dict] = field(default_factory=list)

    # Whisper
    whisper_language: Optional[str] = None
    whisper_summary: Optional[str] = None

    # Essentia
    essentia_bpm: Optional[float] = None
    essentia_bpm_confidence: Optional[float] = None
    essentia_key: Optional[str] = None
    essentia_loudness: Optional[float] = None
    essentia_mood: Optional[dict] = None
    essentia_genre: Optional[dict] = None

    # Bookkeeping
    models_run: list[str] = field(default_factory=list)
    models_failed: list[str] = field(default_factory=list)
    analysis_duration_s: float = 0.0

    @classmethod
    def fallback(cls, file_hash: str) -> "AnalysisResult":
        return cls(
            file_hash=file_hash,
            fallback_only=True,
        )
