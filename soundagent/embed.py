"""
Metadata embedding for each supported format.

WAV/BWF  → iXML chunk + BEXT description via bwfmetaedit (falls back to XMP sidecar)
MP3      → ID3v2 tags via mutagen
FLAC     → Vorbis comments via mutagen
AIFF     → ID3 tags via mutagen (AIFF supports embedded ID3)
All else → XMP sidecar (<filename>.xmp alongside the audio file)

NOTE: The exact Basehead iXML field mapping is not publicly documented and
must be validated empirically against a live Basehead instance. The USER
block fields used here match commonly reported community conventions.
"""

import logging
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

from soundagent.ucs import UCSFields

log = logging.getLogger("soundagent.embed")

_EXT_WAV  = frozenset({".wav", ".bwf"})
_EXT_MP3  = frozenset({".mp3"})
_EXT_FLAC = frozenset({".flac"})
_EXT_AIFF = frozenset({".aiff", ".aif"})

_XMP = """\
<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description rdf:about=""
      xmlns:dc="http://purl.org/dc/elements/1.1/"
      xmlns:sa="http://soundagent/ns/1.0/">
      <dc:title>{fx_name}</dc:title>
      <dc:description>{description}</dc:description>
      <sa:Category>{category}</sa:Category>
      <sa:Subcategory>{subcategory}</sa:Subcategory>
      <sa:CatID>{cat_id}</sa:CatID>
      <sa:Keywords>{keywords}</sa:Keywords>
      <sa:Mood>{mood}</sa:Mood>
      <sa:Energy>{energy}</sa:Energy>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>"""


# ── iXML builder ──────────────────────────────────────────────────────────────

def build_ixml(ucs: UCSFields, original_filename: str | None = None) -> str:
    root = ET.Element("IXML")

    speed = ET.SubElement(root, "SPEED")
    ET.SubElement(speed, "NOTE").text = ucs.description

    user = ET.SubElement(root, "USER")
    fields: dict[str, str] = {
        "CATEGORY":    ucs.category,
        "SUBCATEGORY": ucs.subcategory,
        "FXNAME":      ucs.fx_name,
        "CATID":       ucs.cat_id,
        "KEYWORDS":    ucs.keywords,
        "MOOD":        ucs.mood,
        "ENERGY":      ucs.energy,
    }
    if original_filename:
        fields["ORIGFILENAME"] = original_filename
    if ucs.bpm is not None:
        fields["BPM"] = str(int(ucs.bpm))
    if ucs.key is not None:
        fields["KEY"] = ucs.key

    for tag, value in fields.items():
        ET.SubElement(user, tag).text = value

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


# ── XMP sidecar (universal fallback) ─────────────────────────────────────────

def write_xmp_sidecar(path: Path, ucs: UCSFields) -> Path:
    xmp_path = path.with_suffix(path.suffix + ".xmp")
    content = _XMP.format(
        fx_name=escape(ucs.fx_name),
        description=escape(ucs.description),
        category=escape(ucs.category),
        subcategory=escape(ucs.subcategory),
        cat_id=escape(ucs.cat_id),
        keywords=escape(ucs.keywords),
        mood=escape(ucs.mood),
        energy=escape(ucs.energy),
    )
    xmp_path.write_text(content, encoding="utf-8")
    log.debug(f"XMP sidecar → {xmp_path.name}")
    return xmp_path


# ── WAV/BWF via bwfmetaedit ───────────────────────────────────────────────────

def _bwfmetaedit_write(path: Path, ucs: UCSFields, original_filename: str | None = None) -> None:
    xml = build_ixml(ucs, original_filename)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", delete=False, encoding="utf-8"
    ) as f:
        f.write(xml)
        tmp = Path(f.name)
    try:
        subprocess.run(
            ["bwfmetaedit", f"--in-iXML={tmp}", str(path)],
            check=True, capture_output=True, text=True,
        )
        # BEXT Description field (256 char limit per spec)
        subprocess.run(
            ["bwfmetaedit", f"--bext-Description={ucs.description[:256]}", str(path)],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"bwfmetaedit failed: {e.stderr.strip()}")
    finally:
        tmp.unlink(missing_ok=True)


def _embed_wav(path: Path, ucs: UCSFields, original_filename: str | None = None) -> None:
    try:
        _bwfmetaedit_write(path, ucs, original_filename)
    except FileNotFoundError:
        log.warning(
            f"bwfmetaedit not found — writing XMP sidecar for {path.name}. "
            "Install bwfmetaedit and add it to PATH for embedded iXML support."
        )
        write_xmp_sidecar(path, ucs)


# ── MP3 via mutagen ID3 ───────────────────────────────────────────────────────

def _embed_mp3(path: Path, ucs: UCSFields) -> None:
    from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, COMM, TCON, TXXX, TBPM

    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        tags = ID3()

    tags.delall("TIT2")
    tags.add(TIT2(encoding=3, text=ucs.fx_name))
    tags.delall("COMM")
    tags.add(COMM(encoding=3, lang="eng", desc="", text=ucs.description))
    tags.delall("TCON")
    tags.add(TCON(encoding=3, text=f"{ucs.category}/{ucs.subcategory}"))

    for desc, value in [
        ("CatID",    ucs.cat_id),
        ("Keywords", ucs.keywords),
        ("Mood",     ucs.mood),
        ("Energy",   ucs.energy),
    ]:
        tags.delall(f"TXXX:{desc}")
        tags.add(TXXX(encoding=3, desc=desc, text=value))

    if ucs.bpm is not None:
        tags.delall("TBPM")
        tags.add(TBPM(encoding=3, text=str(int(ucs.bpm))))

    tags.save(str(path), v2_version=3)


# ── FLAC via mutagen Vorbis comments ─────────────────────────────────────────

def _embed_flac(path: Path, ucs: UCSFields) -> None:
    from mutagen.flac import FLAC

    audio = FLAC(str(path))
    audio["title"]       = ucs.fx_name
    audio["description"] = ucs.description
    audio["comment"]     = ucs.description
    audio["category"]    = ucs.category.lower()
    audio["subcategory"] = ucs.subcategory.lower()
    audio["catid"]       = ucs.cat_id
    audio["keywords"]    = ucs.keywords
    audio["mood"]        = ucs.mood
    audio["energy"]      = ucs.energy
    if ucs.bpm is not None:
        audio["bpm"] = str(int(ucs.bpm))
    if ucs.key is not None:
        audio["key"] = ucs.key
    audio.save()


# ── AIFF via mutagen ID3 ──────────────────────────────────────────────────────

def _embed_aiff(path: Path, ucs: UCSFields) -> None:
    from mutagen.aiff import AIFF
    from mutagen.id3 import TIT2, COMM, TCON, TXXX

    audio = AIFF(str(path))
    if audio.tags is None:
        audio.add_tags()

    audio.tags.add(TIT2(encoding=3, text=ucs.fx_name))
    audio.tags.add(COMM(encoding=3, lang="eng", desc="", text=ucs.description))
    audio.tags.add(TCON(encoding=3, text=f"{ucs.category}/{ucs.subcategory}"))
    for desc, value in [
        ("CatID",    ucs.cat_id),
        ("Keywords", ucs.keywords),
        ("Mood",     ucs.mood),
        ("Energy",   ucs.energy),
    ]:
        audio.tags.add(TXXX(encoding=3, desc=desc, text=value))
    audio.save()


# ── Public dispatch ───────────────────────────────────────────────────────────

def embed(path: Path, ucs: UCSFields, original_filename: str | None = None) -> None:
    """Embed UCS metadata into path in the format appropriate for its extension."""
    ext = path.suffix.lower()
    if ext in _EXT_WAV:
        _embed_wav(path, ucs, original_filename)
    elif ext in _EXT_MP3:
        _embed_mp3(path, ucs)
    elif ext in _EXT_FLAC:
        _embed_flac(path, ucs)
    elif ext in _EXT_AIFF:
        _embed_aiff(path, ucs)
    else:
        write_xmp_sidecar(path, ucs)
