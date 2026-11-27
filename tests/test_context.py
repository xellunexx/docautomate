from docautomate.context import PLACEHOLDERS, Blank, assemble, flatten, missing_fields, sample_context


def test_placeholder_catalogue_matches_context():
    """Every documented placeholder exists in the context and vice versa (no silent blanks)."""
    keys = set(flatten(sample_context()))
    assert keys == set(PLACEHOLDERS), (keys ^ set(PLACEHOLDERS))


def test_blank_prints_dots_but_is_false():
    b = Blank()
    assert str(b).startswith("……") and not b


def test_female_candidate_and_representative():
    ctx = assemble({"name_cyr": "Иванова Мария", "gender": "F"}, {"name": "X", "rep_gender": "F"}, {}, {},
                   {"name": "t"})
    assert ctx["candidate"]["roden"] == "родена"
    assert ctx["candidate"]["title"] == "г-жа"
    assert ctx["employer"]["rep_dolupodpisan"] == "Долуподписаната"
    assert ctx["employer"]["rep_v_kachestvoto"] == "в качеството ѝ"


def test_unknown_rep_gender_uses_neutral_form():
    ctx = assemble({}, {"name": "X"}, {}, {}, {"name": "t"})
    assert ctx["employer"]["rep_v_kachestvoto"] == "в качеството си"


def test_missing_fields_lists_only_used_empty():
    ctx = sample_context()
    assert missing_fields(ctx, {"candidate.name_cyr", "candidate.lnch", "case.is_extension"}) == ["candidate.lnch"]


def test_passport_issuer_defaults_to_citizenship():
    ctx = sample_context()
    assert ctx["candidate"]["passport_issued_by"] == "Република Узбекистан"
