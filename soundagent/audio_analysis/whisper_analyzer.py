import logging
from typing import Optional

log = logging.getLogger("soundagent.audio_analysis.whisper")

_WHISPER_MODELS: dict = {}


def analyse(wav_path: str, audio_cfg: dict, anthropic_api_key: str) -> dict:
    """
    Transcribe speech using Whisper. Summarises long transcripts via Claude.

    Returns dict with: language, summary.
    """
    try:
        import whisper
    except ImportError as e:
        raise RuntimeError(f"openai-whisper not installed: {e}")

    model_size = audio_cfg.get("whisper_model", "base")
    if model_size not in _WHISPER_MODELS:
        log.debug(f"Loading Whisper model: {model_size}")
        _WHISPER_MODELS[model_size] = whisper.load_model(model_size)

    model = _WHISPER_MODELS[model_size]
    result = model.transcribe(wav_path)

    transcript: str = result.get("text", "").strip()
    language: Optional[str] = result.get("language")

    words = transcript.split()
    if len(words) <= 30:
        summary = transcript if transcript else None
    else:
        summary = _summarise(transcript, anthropic_api_key)

    return {"language": language, "summary": summary}


def _summarise(transcript: str, api_key: str) -> Optional[str]:
    if not api_key:
        return transcript[:200]  # best-effort truncation when no key

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            messages=[{
                "role": "user",
                "content": (
                    f"Summarise this audio transcript in one sentence:\n\n{transcript[:2000]}"
                ),
            }],
        )
        return response.content[0].text.strip()
    except Exception as e:
        log.debug(f"Whisper summary API call failed (non-fatal): {e}")
        return transcript[:200]
