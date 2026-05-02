import tempfile
from pathlib import Path

from soundagent.dedup import sha256


def test_sha256_consistent():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
        f.write(b"fake audio data")
        p = Path(f.name)
    assert sha256(p) == sha256(p)


def test_sha256_different_for_different_content():
    with tempfile.NamedTemporaryFile(delete=False) as a, tempfile.NamedTemporaryFile(delete=False) as b:
        a.write(b"audio data one")
        b.write(b"audio data two")
        pa, pb = Path(a.name), Path(b.name)
    assert sha256(pa) != sha256(pb)


def test_sha256_returns_hex_string():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"data")
        p = Path(f.name)
    h = sha256(p)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
