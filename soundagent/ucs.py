"""
UCS (Universal Category System) field mapper.

Converts EnrichmentResult into UCS-compatible field layout for Basehead import.
CatID values follow the UCS standard naming conventions.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from soundagent.enrichment import EnrichmentResult

# UCS CatID map — (category, subcategory) → UCS CatID
CATID_MAP: dict[tuple[str, str], str] = {
    ("field",     "nature"):      "AMB-NATU",
    ("field",     "urban"):       "AMB-URBN",
    ("field",     "industrial"):  "AMB-INDU",
    ("field",     "interior"):    "AMB-INT",
    ("sfx",       "impacts"):     "SFX-IMPA",
    ("sfx",       "ambience"):    "SFX-AMBI",
    ("sfx",       "foley"):       "FLY",
    ("sfx",       "designed"):    "SFX-DSGN",
    ("music",     "loops"):       "MUS-LOOP",
    ("music",     "stems"):       "MUS-STEM",
    ("music",     "beds"):        "MUS-BEDS",
    ("music",     "stingers"):    "MUS-STIN",
    ("broadcast", "idents"):      "BRD-IDNT",
    ("broadcast", "vo"):          "BRD-VO",
    ("broadcast", "transitions"): "BRD-TRAN",
}


@dataclass
class UCSFields:
    category: str        # uppercased  e.g. SFX
    subcategory: str     # uppercased  e.g. IMPACTS
    cat_id: str          # e.g. SFX-IMPA
    fx_name: str         # human-readable title derived from filename stem
    description: str
    keywords: str        # comma-separated tags
    mood: str
    energy: str
    bpm: Optional[float]
    key: Optional[str]


def map_to_ucs(result: EnrichmentResult, filename: str) -> UCSFields:
    cat_id = CATID_MAP.get((result.category, result.subcategory), "UNCL")
    stem = Path(filename).stem.replace("_", " ").replace("-", " ")
    fx_name = stem.title()
    return UCSFields(
        category=result.category.upper(),
        subcategory=result.subcategory.upper(),
        cat_id=cat_id,
        fx_name=fx_name,
        description=result.description,
        keywords=", ".join(result.tags),
        mood=result.mood,
        energy=result.energy,
        bpm=result.bpm,
        key=result.key,
    )
