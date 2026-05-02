from pathlib import Path
from unittest.mock import patch

import pytest

from soundagent.ffprobe import extract


def test_ffprobe_not_found():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(RuntimeError, match="ffprobe not found"):
            extract(Path("dummy.wav"))


def test_no_audio_stream_raises():
    import subprocess
    fake_output = '{"streams": [], "format": {}}'
    mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=fake_output, stderr="")
    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(ValueError, match="No audio stream"):
            extract(Path("dummy.wav"))
