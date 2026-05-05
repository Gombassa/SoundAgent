"""Tests for AudioCLIPTagger vocabulary system.

All tests operate on the class directly to avoid the module-level singleton.
ML models are never loaded — torch tensors are constructed inline.
"""

import yaml
import pytest
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock

from soundagent.audio_analysis.audioclip_analyzer import AudioCLIPTagger


# ── Vocabulary loading ────────────────────────────────────────────────────────

def test_vocabulary_loads_expected_categories(tmp_path):
    vocab = {
        "environment": ["indoor", "outdoor", "forest"],
        "weather": ["rain", "wind", "thunder"],
        "water": ["river", "waterfall"],
        "fauna": ["bird song", "crickets"],
        "human": ["speech", "footsteps on gravel"],
        "transport": ["car", "train"],
        "texture": ["continuous tone", "silence"],
    }
    vocab_path = tmp_path / "vocab.yaml"
    vocab_path.write_text(yaml.dump(vocab))

    tagger = AudioCLIPTagger("fake.pt", str(vocab_path), {})
    tagger._available = True
    tagger._load_vocab()

    assert set(tagger._tag_to_category.values()) >= {
        "environment", "weather", "water", "fauna", "human", "transport", "texture"
    }
    assert len(tagger._vocab) == 16


def test_vocabulary_loads_project_file():
    """The checked-in config/tag_vocabulary.yaml must parse and contain all 7 categories."""
    vocab_path = Path(__file__).parent.parent / "config" / "tag_vocabulary.yaml"
    assert vocab_path.exists(), "config/tag_vocabulary.yaml missing from repo"

    with open(vocab_path) as fh:
        raw = yaml.safe_load(fh)

    required = {"environment", "weather", "water", "fauna", "human", "transport", "texture"}
    assert required <= set(raw.keys()), f"Missing categories: {required - set(raw.keys())}"
    total_tags = sum(len(v) for v in raw.values())
    assert total_tags >= 50, f"Expected at least 50 tags, got {total_tags}"


# ── Reverse lookup dict ───────────────────────────────────────────────────────

def test_reverse_lookup_correct(tmp_path):
    vocab = {
        "weather": ["rain", "wind"],
        "fauna": ["crickets", "bird song"],
    }
    vocab_path = tmp_path / "vocab.yaml"
    vocab_path.write_text(yaml.dump(vocab))

    tagger = AudioCLIPTagger("fake.pt", str(vocab_path), {})
    tagger._available = True
    tagger._load_vocab()

    assert tagger._tag_to_category["rain"] == "weather"
    assert tagger._tag_to_category["wind"] == "weather"
    assert tagger._tag_to_category["crickets"] == "fauna"
    assert tagger._tag_to_category["bird song"] == "fauna"
    assert len(tagger._tag_to_category) == 4


def test_reverse_lookup_all_tags_present(tmp_path):
    vocab = {
        "a": ["tag1", "tag2", "tag3"],
        "b": ["tag4"],
    }
    vocab_path = tmp_path / "vocab.yaml"
    vocab_path.write_text(yaml.dump(vocab))

    tagger = AudioCLIPTagger("fake.pt", str(vocab_path), {})
    tagger._available = True
    tagger._load_vocab()

    assert set(tagger._tag_to_category.keys()) == {"tag1", "tag2", "tag3", "tag4"}


# ── Threshold filtering and sort order ───────────────────────────────────────

def test_threshold_and_sort(tmp_path):
    import torch

    vocab = {
        "environment": ["indoor", "outdoor", "forest"],
        "weather": ["rain", "wind"],
    }
    vocab_path = tmp_path / "vocab.yaml"
    vocab_path.write_text(yaml.dump(vocab))

    tagger = AudioCLIPTagger(
        "fake.pt",
        str(vocab_path),
        {"audioclip_threshold": 0.25, "audioclip_max_tags": 10},
    )
    tagger._available = True
    tagger._load_vocab()

    vocab_size = len(tagger._vocab)  # 5

    # Fake normalised text embeddings: orthonormal basis
    tagger._text_embeddings = torch.eye(vocab_size)
    tagger._initialized = True

    # Audio is aligned with "indoor" (index 0) — score 1.0; all others 0.0
    fake_audio = torch.zeros(1, vocab_size)
    fake_audio[0, 0] = 1.0

    mock_model = MagicMock()
    mock_model.encode_audio.return_value = fake_audio
    tagger._model = mock_model

    waveform = np.zeros(44100, dtype=np.float32)
    tags, raw_scores = tagger.analyse(waveform, 44100)

    # Only "indoor" exceeds threshold 0.25
    assert len(tags) == 1
    assert tags[0]["tag"] == "indoor"
    assert tags[0]["category"] == "environment"
    assert tags[0]["score"] == 1.0

    # raw_scores covers every vocabulary item
    assert len(raw_scores) == vocab_size
    assert raw_scores["indoor"] == 1.0
    for tag in ["outdoor", "forest", "rain", "wind"]:
        assert raw_scores[tag] == 0.0


def test_scores_sorted_descending(tmp_path):
    import torch

    vocab = {"cat": ["a", "b", "c"]}
    vocab_path = tmp_path / "vocab.yaml"
    vocab_path.write_text(yaml.dump(vocab))

    tagger = AudioCLIPTagger(
        "fake.pt", str(vocab_path), {"audioclip_threshold": 0.0, "audioclip_max_tags": 10}
    )
    tagger._available = True
    tagger._load_vocab()

    # Scores in shuffled order: b=0.8, c=0.5, a=0.3
    fake_scores = torch.tensor([[0.3, 0.8, 0.5]])
    tagger._text_embeddings = torch.eye(3)
    tagger._initialized = True

    mock_model = MagicMock()
    mock_model.encode_audio.return_value = fake_scores
    tagger._model = mock_model

    tags, _ = tagger.analyse(np.zeros(44100, dtype=np.float32), 44100)

    score_seq = [t["score"] for t in tags]
    assert score_seq == sorted(score_seq, reverse=True)
    assert tags[0]["tag"] == "b"


def test_max_tags_cap(tmp_path):
    import torch

    vocab = {"cat": [f"tag{i}" for i in range(20)]}
    vocab_path = tmp_path / "vocab.yaml"
    vocab_path.write_text(yaml.dump(vocab))

    tagger = AudioCLIPTagger(
        "fake.pt", str(vocab_path), {"audioclip_threshold": 0.0, "audioclip_max_tags": 5}
    )
    tagger._available = True
    tagger._load_vocab()

    tagger._text_embeddings = torch.ones(20, 20) / 20
    tagger._initialized = True
    mock_model = MagicMock()
    mock_model.encode_audio.return_value = torch.ones(1, 20)
    tagger._model = mock_model

    tags, _ = tagger.analyse(np.zeros(44100, dtype=np.float32), 44100)
    assert len(tags) <= 5


# ── Empty vocabulary ──────────────────────────────────────────────────────────

def test_empty_vocabulary_returns_empty(tmp_path):
    vocab_path = tmp_path / "vocab.yaml"
    vocab_path.write_text("{}")

    tagger = AudioCLIPTagger("fake.pt", str(vocab_path), {})
    tagger._available = True

    tags, raw_scores = tagger.analyse(np.zeros(44100, dtype=np.float32), 44100)
    assert tags == []
    assert raw_scores == {}


def test_missing_vocabulary_file_returns_empty(tmp_path):
    tagger = AudioCLIPTagger("fake.pt", str(tmp_path / "nonexistent.yaml"), {})
    tagger._available = True

    tags, raw_scores = tagger.analyse(np.zeros(44100, dtype=np.float32), 44100)
    assert tags == []
    assert raw_scores == {}


# ── Graceful degradation ──────────────────────────────────────────────────────

def test_unavailable_returns_empty_no_raise(tmp_path):
    vocab_path = tmp_path / "vocab.yaml"
    vocab_path.write_text(yaml.dump({"cat": ["tag1"]}))

    tagger = AudioCLIPTagger(
        "/nonexistent/weights.pt", str(vocab_path), {}
    )
    # Don't set _available — let is_available() check the (missing) path

    tags, raw_scores = tagger.analyse(np.zeros(44100, dtype=np.float32), 44100)
    assert tags == []
    assert raw_scores == {}


def test_raw_scores_rounded_to_4dp(tmp_path):
    import torch

    vocab = {"cat": ["a", "b"]}
    vocab_path = tmp_path / "vocab.yaml"
    vocab_path.write_text(yaml.dump(vocab))

    tagger = AudioCLIPTagger("fake.pt", str(vocab_path), {"audioclip_threshold": 0.0})
    tagger._available = True
    tagger._load_vocab()

    tagger._text_embeddings = torch.eye(2)
    tagger._initialized = True

    mock_model = MagicMock()
    mock_model.encode_audio.return_value = torch.tensor([[0.123456789, 0.987654321]])
    tagger._model = mock_model

    _, raw_scores = tagger.analyse(np.zeros(44100, dtype=np.float32), 44100)

    for score in raw_scores.values():
        assert score == round(score, 4)
