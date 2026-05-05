import logging
import tempfile
import time

from soundagent.audio_analysis.result import AnalysisResult
from soundagent.audio_analysis import preprocessor
from soundagent.audio_analysis import yamnet_analyzer
from soundagent.audio_analysis import whisper_analyzer
from soundagent.audio_analysis import audioclip_analyzer
from soundagent.audio_analysis import essentia_analyzer

log = logging.getLogger("soundagent.audio_analysis.pipeline")


def analyse(
    filepath: str,
    file_hash: str,
    audio_cfg: dict,
    duration_s: float = 0.0,
    anthropic_api_key: str = "",
) -> AnalysisResult:
    """
    Run audio analysis models on a file and return an AnalysisResult.

    If audio_analysis.enabled is False or all models fail, returns a
    fallback result so the tick pipeline continues with filename-only enrichment.
    """
    if not audio_cfg.get("enabled", True):
        return AnalysisResult.fallback(file_hash)

    start = time.monotonic()
    tmp_dir = tempfile.mkdtemp()

    yamnet_classes: list[str] = []
    yamnet_embedding = None
    content_type = "sfx_or_field"
    speech_score = 0.0
    audioclip_matches: list[dict] = []
    audioclip_raw_scores: dict = {}
    whisper_language = None
    whisper_summary = None
    essentia_bpm = None
    essentia_bpm_confidence = None
    essentia_key = None
    essentia_loudness = None
    essentia_mood = None
    essentia_genre = None
    librosa_bpm = None
    librosa_bpm_confidence = None
    librosa_key = None
    librosa_loudness_rms = None
    librosa_dynamic_complexity = None
    librosa_spectral_centroid = None
    librosa_zero_crossing_rate = None
    librosa_source = None
    models_run: list[str] = []
    models_failed: list[str] = []

    max_analysis_s = audio_cfg.get("max_analysis_duration_s", 120)
    long_file = duration_s > max_analysis_s
    truncate_s = audio_cfg.get("truncate_waveform_s", 60)
    speech_threshold = audio_cfg.get("speech_threshold", 0.4)

    try:
        import shutil
        try:
            # Preprocess: 16kHz for YAMNet/Whisper, 44.1kHz for AudioCLIP
            wav_16k = preprocessor.to_wav(filepath, tmp_dir, 16000)
            wav_44k = preprocessor.to_wav(filepath, tmp_dir, 44100)
            waveform_16k, sr_16k = preprocessor.load_waveform_float32(wav_16k)

            analysis_waveform = (
                preprocessor.truncate_waveform(waveform_16k, sr_16k, truncate_s)
                if long_file else waveform_16k
            )
        except Exception as exc:
            log.error(f"Audio preprocessing failed for {filepath}: {exc}")
            return AnalysisResult.fallback(file_hash)

        # ── YAMNet ────────────────────────────────────────────────────────────
        try:
            yamnet_result = yamnet_analyzer.analyse(analysis_waveform, sr_16k, audio_cfg)
            yamnet_classes = yamnet_result["classes"]
            yamnet_embedding = yamnet_result["embedding"]
            content_type = yamnet_result["content_type"]
            speech_score = yamnet_result["speech_score"]
            models_run.append("yamnet")
        except Exception as exc:
            log.warning(f"YAMNet failed: {exc}")
            models_failed.append("yamnet")

        # ── AudioCLIP ────────────────────────────────────────────────────────
        try:
            waveform_44k, sr_44k = preprocessor.load_waveform_float32(wav_44k)
            if long_file:
                waveform_44k = preprocessor.truncate_waveform(waveform_44k, sr_44k, truncate_s)
            if audioclip_analyzer.is_available(audio_cfg):
                audioclip_matches, audioclip_raw_scores = audioclip_analyzer.analyse(
                    waveform_44k, sr_44k, audio_cfg
                )
                models_run.append("audioclip")
        except Exception as exc:
            log.warning(f"AudioCLIP failed: {exc}")
            models_failed.append("audioclip")

        # ── Whisper ──────────────────────────────────────────────────────────
        run_whisper = (
            not long_file
            and (content_type == "speech" or speech_score > speech_threshold)
        )
        if run_whisper:
            try:
                whisper_result = whisper_analyzer.analyse(str(wav_16k), audio_cfg, anthropic_api_key)
                whisper_language = whisper_result["language"]
                whisper_summary = whisper_result["summary"]
                models_run.append("whisper")
            except Exception as exc:
                log.warning(f"Whisper failed: {exc}")
                models_failed.append("whisper")
        elif long_file:
            models_failed.append("whisper")  # skipped, not an error, but track it

        # ── Essentia / librosa ────────────────────────────────────────────────
        run_music = not long_file and content_type == "music"
        if run_music:
            if essentia_analyzer.is_available():
                try:
                    ess = essentia_analyzer.analyse(filepath)
                    essentia_bpm = ess.get("bpm")
                    essentia_bpm_confidence = ess.get("bpm_confidence")
                    essentia_key = ess.get("key")
                    essentia_loudness = ess.get("loudness")
                    essentia_mood = ess.get("mood")
                    essentia_genre = ess.get("genre")
                    models_run.append("essentia")
                except Exception as exc:
                    log.warning(f"Essentia failed: {exc}")
                    models_failed.append("essentia")
            else:
                # Windows fallback: librosa
                from soundagent.audio_analysis import librosa_analyzer
                lib = librosa_analyzer.analyse(filepath)
                if lib is not None:
                    librosa_bpm = lib.get("bpm")
                    librosa_bpm_confidence = lib.get("bpm_confidence")
                    librosa_key = lib.get("key")
                    librosa_loudness_rms = lib.get("loudness_rms")
                    librosa_dynamic_complexity = lib.get("dynamic_complexity")
                    librosa_spectral_centroid = lib.get("spectral_centroid_mean")
                    librosa_zero_crossing_rate = lib.get("zero_crossing_rate_mean")
                    librosa_source = lib.get("source")
                    models_run.append("librosa")
                else:
                    models_failed.append("librosa")
        elif long_file and content_type == "music":
            models_failed.append("essentia")  # skipped due to length

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    fallback_only = len(models_run) == 0

    return AnalysisResult(
        file_hash=file_hash,
        fallback_only=fallback_only,
        yamnet_classes=yamnet_classes,
        yamnet_embedding=yamnet_embedding,
        content_type=content_type,
        speech_score=speech_score,
        audioclip_matches=audioclip_matches,
        audioclip_raw_scores=audioclip_raw_scores,
        whisper_language=whisper_language,
        whisper_summary=whisper_summary,
        essentia_bpm=essentia_bpm,
        essentia_bpm_confidence=essentia_bpm_confidence,
        essentia_key=essentia_key,
        essentia_loudness=essentia_loudness,
        essentia_mood=essentia_mood,
        essentia_genre=essentia_genre,
        librosa_bpm=librosa_bpm,
        librosa_bpm_confidence=librosa_bpm_confidence,
        librosa_key=librosa_key,
        librosa_loudness_rms=librosa_loudness_rms,
        librosa_dynamic_complexity=librosa_dynamic_complexity,
        librosa_spectral_centroid=librosa_spectral_centroid,
        librosa_zero_crossing_rate=librosa_zero_crossing_rate,
        librosa_source=librosa_source,
        models_run=models_run,
        models_failed=models_failed,
        analysis_duration_s=round(time.monotonic() - start, 2),
    )
