"""Tests for soundagent.audio_analysis — mocks all ML libraries."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import numpy as np
import pytest

from soundagent.audio_analysis.result import AnalysisResult
from soundagent.audio_analysis.preprocessor import truncate_waveform


# ── AnalysisResult ────────────────────────────────────────────────────────────

def test_analysis_result_fallback():
    r = AnalysisResult.fallback("abc123")
    assert r.fallback_only is True
    assert r.file_hash == "abc123"
    assert r.yamnet_classes == []
    assert r.audioclip_matches == []
    assert r.content_type == "sfx_or_field"
    assert r.speech_score == 0.0
    assert r.whisper_language is None
    assert r.essentia_bpm is None
    assert r.models_run == []
    assert r.models_failed == []
    assert r.analysis_duration_s == 0.0


# ── preprocessor ─────────────────────────────────────────────────────────────

def test_truncate_waveform_no_truncation():
    samples = np.zeros(16000, dtype=np.float32)
    result = truncate_waveform(samples, 16000, max_seconds=2.0)
    assert len(result) == 16000


def test_truncate_waveform_truncates():
    samples = np.zeros(48000, dtype=np.float32)
    result = truncate_waveform(samples, 16000, max_seconds=2.0)
    assert len(result) == 32000


def test_preprocessor_ffmpeg_args():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        import tempfile
        from soundagent.audio_analysis.preprocessor import to_wav
        with tempfile.TemporaryDirectory() as tmp:
            try:
                to_wav("/some/file.wav", tmp, 16000)
            except Exception:
                pass
        args = mock_run.call_args[0][0]
        assert "16000" in args
        assert "-ac" in args
        assert "1" in args[args.index("-ac") + 1]


# ── pipeline: disabled ────────────────────────────────────────────────────────

def test_pipeline_disabled():
    from soundagent.audio_analysis.pipeline import analyse
    result = analyse("/some/file.wav", "hash1", {"enabled": False}, duration_s=5.0)
    assert result.fallback_only is True
    assert result.file_hash == "hash1"
    assert result.models_run == []


# ── pipeline: all models fail ─────────────────────────────────────────────────

def test_pipeline_all_models_fail():
    from soundagent.audio_analysis.pipeline import analyse

    dummy_waveform = np.zeros(16000, dtype=np.float32)

    with patch("soundagent.audio_analysis.pipeline.preprocessor") as mock_prep, \
         patch("soundagent.audio_analysis.pipeline.yamnet_analyzer") as mock_yamnet, \
         patch("soundagent.audio_analysis.pipeline.audioclip_analyzer") as mock_audioclip, \
         patch("soundagent.audio_analysis.pipeline.whisper_analyzer") as mock_whisper, \
         patch("soundagent.audio_analysis.pipeline.essentia_analyzer") as mock_essentia, \
         patch("shutil.rmtree"):

        mock_prep.to_wav.return_value = Path("/tmp/tmp.wav")
        mock_prep.load_waveform_float32.return_value = (dummy_waveform, 16000)
        mock_prep.truncate_waveform.return_value = dummy_waveform

        mock_yamnet.analyse.side_effect = RuntimeError("TF not installed")
        mock_audioclip.analyse.side_effect = RuntimeError("torch not installed")

        result = analyse("/file.wav", "hash2", {"enabled": True}, duration_s=5.0)

    assert result.fallback_only is True
    assert "yamnet" in result.models_failed
    assert "audioclip" in result.models_failed


# ── YAMNet content-type detection ────────────────────────────────────────────

def test_yamnet_content_type_speech():
    from soundagent.audio_analysis import yamnet_analyzer
    import sys

    class_names = ["Speech", "Music", "Animal", "Gunshot", "Conversation"]

    raw_scores = np.array([[0.8, 0.05, 0.01, 0.01, 0.3]])  # Speech + Conversation high
    raw_embeddings = np.ones((1, 1024))

    fake_scores = MagicMock()
    fake_scores.numpy.return_value = raw_scores
    fake_embeddings = MagicMock()
    fake_embeddings.numpy.return_value = raw_embeddings

    mock_model = MagicMock()
    mock_model.return_value = (fake_scores, fake_embeddings, None)

    mock_tf = MagicMock()
    mock_tf.constant.side_effect = lambda x, dtype=None: x

    with patch.object(yamnet_analyzer, "_get_model", return_value=(mock_model, class_names)), \
         patch.dict(sys.modules, {"tensorflow": mock_tf}):
        result = yamnet_analyzer.analyse(np.zeros(16000, dtype=np.float32), 16000, {})
    assert result["content_type"] == "speech"


def test_yamnet_requires_16khz():
    from soundagent.audio_analysis import yamnet_analyzer
    with pytest.raises(ValueError, match="16kHz"):
        yamnet_analyzer.analyse(np.zeros(1000, dtype=np.float32), 44100, {})


# ── Whisper: only runs on speech ──────────────────────────────────────────────

def test_whisper_runs_only_on_speech():
    from soundagent.audio_analysis.pipeline import analyse

    dummy_wav = np.zeros(16000, dtype=np.float32)

    with patch("soundagent.audio_analysis.pipeline.preprocessor") as mock_prep, \
         patch("soundagent.audio_analysis.pipeline.yamnet_analyzer") as mock_yamnet, \
         patch("soundagent.audio_analysis.pipeline.audioclip_analyzer") as mock_audioclip, \
         patch("soundagent.audio_analysis.pipeline.whisper_analyzer") as mock_whisper, \
         patch("soundagent.audio_analysis.pipeline.essentia_analyzer"), \
         patch("shutil.rmtree"):

        mock_prep.to_wav.return_value = Path("/tmp/tmp.wav")
        mock_prep.load_waveform_float32.return_value = (dummy_wav, 16000)
        mock_prep.truncate_waveform.return_value = dummy_wav
        mock_yamnet.analyse.return_value = {
            "classes": ["Music"], "embedding": [], "content_type": "music", "speech_score": 0.1,
        }
        mock_audioclip.analyse.return_value = []
        mock_whisper.analyse.return_value = {"language": "en", "summary": "test"}

        result = analyse("/file.wav", "h", {"enabled": True}, duration_s=5.0)

    # content_type is "music" → Whisper should NOT have run
    mock_whisper.analyse.assert_not_called()


# ── Essentia: only runs on music ──────────────────────────────────────────────

def test_essentia_runs_only_on_music():
    from soundagent.audio_analysis.pipeline import analyse

    dummy_wav = np.zeros(16000, dtype=np.float32)

    with patch("soundagent.audio_analysis.pipeline.preprocessor") as mock_prep, \
         patch("soundagent.audio_analysis.pipeline.yamnet_analyzer") as mock_yamnet, \
         patch("soundagent.audio_analysis.pipeline.audioclip_analyzer") as mock_audioclip, \
         patch("soundagent.audio_analysis.pipeline.whisper_analyzer"), \
         patch("soundagent.audio_analysis.pipeline.essentia_analyzer") as mock_essentia, \
         patch("shutil.rmtree"):

        mock_prep.to_wav.return_value = Path("/tmp/tmp.wav")
        mock_prep.load_waveform_float32.return_value = (dummy_wav, 16000)
        mock_prep.truncate_waveform.return_value = dummy_wav
        mock_yamnet.analyse.return_value = {
            "classes": ["Speech"], "embedding": [], "content_type": "speech", "speech_score": 0.8,
        }
        mock_audioclip.analyse.return_value = []

        result = analyse("/file.wav", "h", {"enabled": True}, duration_s=5.0)

    # content_type is "speech" → Essentia should NOT have run
    mock_essentia.analyse.assert_not_called()


# ── AudioCLIP: skips missing weights ─────────────────────────────────────────

def test_audioclip_skips_missing_weights():
    from soundagent.audio_analysis import audioclip_analyzer
    audioclip_analyzer._WEIGHTS_CHECKED = False
    audioclip_analyzer._WEIGHTS_AVAILABLE = False

    with patch("pathlib.Path.exists", return_value=False):
        with pytest.raises(RuntimeError, match="weights not available"):
            audioclip_analyzer.analyse(
                np.zeros(44100, dtype=np.float32), 44100,
                {"audioclip_weights_path": "/nonexistent/AudioCLIP.pt"},
            )


# ── Long file: slow models skipped ───────────────────────────────────────────

def test_long_file_skips_whisper_and_essentia():
    from soundagent.audio_analysis.pipeline import analyse

    dummy_wav = np.zeros(16000, dtype=np.float32)

    with patch("soundagent.audio_analysis.pipeline.preprocessor") as mock_prep, \
         patch("soundagent.audio_analysis.pipeline.yamnet_analyzer") as mock_yamnet, \
         patch("soundagent.audio_analysis.pipeline.audioclip_analyzer") as mock_audioclip, \
         patch("soundagent.audio_analysis.pipeline.whisper_analyzer") as mock_whisper, \
         patch("soundagent.audio_analysis.pipeline.essentia_analyzer") as mock_essentia, \
         patch("shutil.rmtree"):

        mock_prep.to_wav.return_value = Path("/tmp/tmp.wav")
        mock_prep.load_waveform_float32.return_value = (dummy_wav, 16000)
        mock_prep.truncate_waveform.return_value = dummy_wav
        mock_yamnet.analyse.return_value = {
            "classes": ["Music"], "embedding": [], "content_type": "music", "speech_score": 0.1,
        }
        mock_audioclip.analyse.return_value = []

        # duration_s=200 exceeds default max_analysis_duration_s=120 → long_file=True
        result = analyse("/file.wav", "h", {"enabled": True}, duration_s=200.0)

    mock_whisper.analyse.assert_not_called()
    mock_essentia.analyse.assert_not_called()
