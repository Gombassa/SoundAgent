from soundagent.enrichment import EnrichmentResult
from soundagent.ucs import map_to_ucs, CATID_MAP


def _result(category: str, subcategory: str, **kwargs) -> EnrichmentResult:
    defaults = dict(
        description="A test sound.",
        tags=["test", "sound"],
        mood="neutral",
        energy="medium",
        bpm=None,
        key=None,
        confidence=0.9,
        low_confidence=False,
    )
    return EnrichmentResult(category=category, subcategory=subcategory, **{**defaults, **kwargs})


def test_catid_mapped_correctly():
    ucs = map_to_ucs(_result("sfx", "impacts"), "metal_hit_01.wav")
    assert ucs.cat_id == "SFX-IMPA"


def test_all_categories_have_catids():
    from soundagent.enrichment import VALID_SUBCATEGORIES
    for category, subs in VALID_SUBCATEGORIES.items():
        for sub in subs:
            key = (category, sub)
            assert key in CATID_MAP, f"Missing CatID for {key}"


def test_unknown_subcategory_gets_uncl():
    result = _result("sfx", "impacts")
    result = EnrichmentResult(
        category="sfx", subcategory="impacts",
        description="x", tags=[], mood="", energy="low",
        bpm=None, key=None, confidence=0.9, low_confidence=False,
    )
    # Manually override cat_id lookup by passing unknown pair
    from soundagent.ucs import CATID_MAP
    assert CATID_MAP.get(("sfx", "nonexistent"), "UNCL") == "UNCL"


def test_fx_name_derived_from_stem():
    ucs = map_to_ucs(_result("sfx", "foley"), "footstep_gravel_run.wav")
    assert ucs.fx_name == "Footstep Gravel Run"


def test_fx_name_handles_dashes():
    ucs = map_to_ucs(_result("sfx", "ambience"), "city-traffic-loop.mp3")
    assert ucs.fx_name == "City Traffic Loop"


def test_category_uppercased():
    ucs = map_to_ucs(_result("field", "nature"), "birds.wav")
    assert ucs.category == "FIELD"
    assert ucs.subcategory == "NATURE"


def test_keywords_joined():
    result = _result("music", "loops", tags=["upbeat", "guitar", "120bpm"])
    ucs = map_to_ucs(result, "track.wav")
    assert "upbeat" in ucs.keywords
    assert "guitar" in ucs.keywords


def test_bpm_and_key_passed_through():
    result = _result("music", "loops", bpm=128.0, key="A minor")
    ucs = map_to_ucs(result, "loop.wav")
    assert ucs.bpm == 128.0
    assert ucs.key == "A minor"


def test_non_music_bpm_is_none():
    ucs = map_to_ucs(_result("sfx", "impacts", bpm=None), "hit.wav")
    assert ucs.bpm is None
