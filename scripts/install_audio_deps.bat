@echo off
echo Installing SoundAgent P7 audio analysis dependencies...
echo.

echo [1/5] Installing TensorFlow + TensorFlow Hub (YAMNet)...
pip install tensorflow tensorflow-hub
echo.

echo [2/5] Installing OpenAI Whisper...
pip install openai-whisper
echo.

echo [3/5] Installing PyTorch + torchaudio (AudioCLIP)...
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
echo.

echo [4/5] Installing soundfile + scipy (audio preprocessing)...
pip install soundfile scipy
echo.

echo [5/5] AudioCLIP — source install required:
echo   git clone https://github.com/AndreyGuzhov/AudioCLIP
echo   pip install -e .\AudioCLIP
echo.
echo   Then download weights (~800 MB) from the AudioCLIP releases page and place at:
echo   models\audioclip\AudioCLIP.pt
echo.

echo Installing librosa (Windows music analysis)...
pip install "librosa>=0.10.0"
echo.

echo NOTE: Essentia is Linux/macOS only via pip.
echo   On Windows, use the essentia-tensorflow wheel from:
echo   https://github.com/MTG/essentia/releases
echo.

echo Done. YAMNet and Whisper weights download automatically on first use.
pause
