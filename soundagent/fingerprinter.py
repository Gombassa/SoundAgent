"""
soundagent/fingerprinter.py

Audio fingerprinting via fpcalc (Chromaprint CLI).
No external library dependencies beyond stdlib.
"""

import base64
import json
import logging
import struct
import subprocess
from pathlib import Path

logger = logging.getLogger("soundagent.fingerprinter")


def _resolve(fpcalc_path: str) -> str:
    """Normalise path separators so Windows subprocess can find relative paths."""
    return str(Path(fpcalc_path))


def is_available(fpcalc_path: str = "fpcalc") -> bool:
    """Return True if the fpcalc binary can be found and executed."""
    try:
        subprocess.run(
            [_resolve(fpcalc_path), "-version"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return True
    except (FileNotFoundError, OSError):
        return False


def generate(filepath: Path, fpcalc_path: str = "fpcalc") -> dict | None:
    """
    Run fpcalc on filepath. Returns:
        {"duration": float, "fingerprint": str}
    Returns None if fpcalc is not found or fails — logs warning, never raises.
    """
    try:
        result = subprocess.run(
            [_resolve(fpcalc_path), "-json", str(filepath)],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            logger.warning(f"fpcalc failed for {filepath.name}: {result.stderr.strip()}")
            return None
        data = json.loads(result.stdout)
        return {"duration": float(data["duration"]), "fingerprint": data["fingerprint"]}
    except FileNotFoundError:
        logger.warning(
            "fpcalc not found — fingerprint matching disabled. "
            "Install from https://acoustid.org/chromaprint"
        )
        return None
    except Exception as exc:
        logger.warning(f"Fingerprint generation failed for {filepath.name}: {exc}")
        return None


def similarity(fp_a: str, fp_b: str) -> float:
    """
    Compare two base64-encoded Chromaprint fingerprint strings.
    Returns similarity in range 0.0–1.0.
    Uses Hamming distance over the shorter fingerprint length.
    Returns 0.0 on any decode error.
    """
    try:
        a = _decode_fingerprint(fp_a)
        b = _decode_fingerprint(fp_b)
        if not a or not b:
            return 0.0
        length = min(len(a), len(b))
        total_bits = length * 32
        diff_bits = sum(bin(a[i] ^ b[i]).count("1") for i in range(length))
        return 1.0 - diff_bits / total_bits
    except Exception:
        return 0.0


def _decode_fingerprint(fp: str) -> list[int]:
    """
    Decode base64 Chromaprint fingerprint to list of 32-bit integers.
    Chromaprint uses URL-safe base64 without padding.
    """
    pad = (4 - len(fp) % 4) % 4
    raw = base64.urlsafe_b64decode(fp + "=" * pad)
    n = len(raw) // 4
    return list(struct.unpack(f"<{n}I", raw[: n * 4]))
