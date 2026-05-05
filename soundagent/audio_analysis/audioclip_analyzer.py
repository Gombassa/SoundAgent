import logging
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("soundagent.audio_analysis.audioclip")

# ── Singleton tagger (one per process) ────────────────────────────────────────

_TAGGER: Optional["AudioCLIPTagger"] = None


class AudioCLIPTagger:
    """
    Loads AudioCLIP once, pre-computes normalised text embeddings for the full
    tag vocabulary at startup, and serves per-file inference via a single matmul.
    """

    def __init__(self, weights_path: str, vocab_path: str, audio_cfg: dict):
        self._weights_path = weights_path
        self._vocab_path = Path(vocab_path)
        self._audio_cfg = audio_cfg
        self._model = None
        self._available: Optional[bool] = None
        self._vocab: list[str] = []
        self._tag_to_category: dict[str, str] = {}
        self._text_embeddings = None   # torch.Tensor shape [V, D], normalised
        self._vocab_mtime: float = 0.0
        self._initialized: bool = False

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        if not Path(self._weights_path).exists():
            log.warning(
                f"AudioCLIP weights not found at {self._weights_path}. "
                "Download AudioCLIP-Partial-Training.pt to enable AudioCLIP tagging."
            )
            self._available = False
            return False
        try:
            from AudioCLIP import AudioCLIP  # noqa: F401
        except ImportError as exc:
            log.warning(f"AudioCLIP not importable: {exc}")
            self._available = False
            return False
        self._available = True
        return True

    # ── Vocabulary loading ────────────────────────────────────────────────────

    def _load_vocab(self) -> None:
        import yaml

        if not self._vocab_path.exists():
            log.error(
                f"Tag vocabulary not found at {self._vocab_path}. "
                "AudioCLIP will return no tags."
            )
            self._vocab = []
            self._tag_to_category = {}
            self._vocab_mtime = 0.0
            return

        try:
            with open(self._vocab_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh)
            if not isinstance(raw, dict):
                raise ValueError("Vocabulary YAML must be a mapping of category → [tags]")

            vocab: list[str] = []
            tag_to_cat: dict[str, str] = {}
            for category, tags in raw.items():
                if not isinstance(tags, list):
                    log.warning(f"Vocabulary category {category!r} is not a list — skipping")
                    continue
                for tag in tags:
                    tag_str = str(tag).strip()
                    if tag_str:
                        vocab.append(tag_str)
                        tag_to_cat[tag_str] = str(category)

            self._vocab = vocab
            self._tag_to_category = tag_to_cat
            self._vocab_mtime = self._vocab_path.stat().st_mtime
            log.info(
                f"Loaded {len(vocab)} tags from {self._vocab_path} "
                f"({len(raw)} categories)"
            )
        except Exception as exc:
            log.error(f"Failed to load tag vocabulary from {self._vocab_path}: {exc}")
            self._vocab = []
            self._tag_to_category = {}
            self._vocab_mtime = 0.0

    # ── Text embedding cache ───────────────────────────────────────────────────

    def _build_text_embeddings(self) -> None:
        import torch

        model = self._get_model()
        # encode_text expects List[List[str]]; each tag is wrapped in a one-item list
        text_input = [[tag] for tag in self._vocab]
        with torch.no_grad():
            text_features = model.encode_text(text=text_input)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)
        self._text_embeddings = text_features
        log.info(f"Pre-computed text embeddings for {len(self._vocab)} vocabulary tags")

    # ── Model loading ──────────────────────────────────────────────────────────

    def _get_model(self):
        if self._model is not None:
            return self._model
        from AudioCLIP import AudioCLIP
        self._model = AudioCLIP(pretrained=self._weights_path)
        self._model.eval()
        return self._model

    # ── Lazy init (once per process) ──────────────────────────────────────────

    def _ensure_ready(self) -> bool:
        """
        Load vocab + build text embeddings on the first call (startup).
        Mtime is checked here; subsequent inference calls skip this entirely.
        """
        if self._initialized:
            return self._available is True and self._text_embeddings is not None

        self._initialized = True

        if not self.is_available():
            return False

        self._load_vocab()

        if not self._vocab:
            return True  # available but empty vocabulary — not an error

        try:
            self._build_text_embeddings()
        except Exception as exc:
            log.warning(f"Failed to build AudioCLIP text embeddings: {exc}")
            return False

        return True

    # ── Per-file inference ────────────────────────────────────────────────────

    def analyse(
        self, waveform: np.ndarray, sample_rate: int
    ) -> tuple[list[dict], dict]:
        """
        Score waveform against the cached vocabulary.

        Returns:
            tags: [{tag, category, score}] above threshold, sorted desc, capped at max_tags
            raw_scores: {tag: score} for every vocabulary item, scores rounded to 4dp
        """
        if not self._ensure_ready():
            return [], {}

        if not self._vocab or self._text_embeddings is None:
            return [], {}

        try:
            import torch
            import torchaudio.transforms as T
        except ImportError as exc:
            raise RuntimeError(f"torch/torchaudio not installed: {exc}")

        model = self._get_model()

        target_sr = 44100
        if sample_rate != target_sr:
            waveform_t = torch.from_numpy(waveform).float().unsqueeze(0)
            resampler = T.Resample(orig_freq=sample_rate, new_freq=target_sr)
            waveform_t = resampler(waveform_t)
        else:
            waveform_t = torch.from_numpy(waveform).float().unsqueeze(0)

        threshold = self._audio_cfg.get("audioclip_threshold", 0.20)
        max_tags = self._audio_cfg.get(
            "audioclip_max_tags",
            self._audio_cfg.get("audioclip_top_n", 15),
        )

        with torch.no_grad():
            audio_features = model.encode_audio(audio=waveform_t.unsqueeze(0))
            audio_features = audio_features / audio_features.norm(dim=-1, keepdim=True)
            scores = (audio_features @ self._text_embeddings.T).squeeze(0)

        scores_np = scores.cpu().numpy()

        raw_scores: dict[str, float] = {
            self._vocab[i]: round(float(scores_np[i]), 4)
            for i in range(len(self._vocab))
        }

        ranked = sorted(
            (
                {
                    "tag": self._vocab[i],
                    "category": self._tag_to_category.get(self._vocab[i], ""),
                    "score": round(float(scores_np[i]), 4),
                }
                for i in range(len(self._vocab))
            ),
            key=lambda x: x["score"],
            reverse=True,
        )

        tags = [r for r in ranked[:max_tags] if r["score"] >= threshold]
        return tags, raw_scores


# ── Module-level singleton management ────────────────────────────────────────

def _get_tagger(audio_cfg: dict) -> "AudioCLIPTagger":
    global _TAGGER
    if _TAGGER is None:
        weights_path = audio_cfg.get(
            "audioclip_weights_path",
            "models/audioclip/AudioCLIP-Partial-Training.pt",
        )
        vocab_path = audio_cfg.get("tag_vocabulary_path", "config/tag_vocabulary.yaml")
        _TAGGER = AudioCLIPTagger(weights_path, vocab_path, audio_cfg)
    return _TAGGER


def is_available(audio_cfg: dict) -> bool:
    """Return True if the AudioCLIP weights exist and the package is importable."""
    return _get_tagger(audio_cfg).is_available()


def analyse(
    waveform: np.ndarray, sample_rate: int, audio_cfg: dict
) -> tuple[list[dict], dict]:
    """
    Module-level entry point. Never raises.

    Returns (tags, raw_scores):
      - tags: [{tag, category, score}] above threshold, sorted desc
      - raw_scores: {tag: score} for every vocab item
      - Returns ([], {}) when AudioCLIP is unavailable or inference fails.
    """
    try:
        tagger = _get_tagger(audio_cfg)
        if not tagger.is_available():
            return [], {}
        return tagger.analyse(waveform, sample_rate)
    except Exception as exc:
        log.warning(f"AudioCLIP inference failed: {exc}")
        return [], {}
