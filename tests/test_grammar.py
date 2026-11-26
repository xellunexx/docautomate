import pytest

from docautomate import grammar


def test_words_bg_and_ru():
    assert grammar.words_bg(6) == "шест"
    assert grammar.words_bg(3) == "три"
    assert grammar.words_bg(36) == "тридесет и шест"
    assert grammar.words_ru(6) == "шесть"
    assert grammar.words_ru(0) == "ноль"
    assert grammar.words_ru(21) == "двадцать один"


@pytest.mark.parametrize("n,form", [(1, "месяц"), (2, "месяца"), (5, "месяцев"), (11, "месяцев"),
                                    (21, "месяц"), (36, "месяцев"), (3, "месяца")])
def test_months_ru(n, form):
    assert grammar.months_ru(n) == form


def test_months_bg_and_term():
    assert grammar.months_bg(1) == "месец"
    assert grammar.months_bg(6) == "месеца"
    assert grammar.term_text_bg(36) == "3 години"
    assert grammar.term_text_bg(12) == "1 година"
    assert grammar.term_text_bg(3) == "3 месеца"


def test_dates():
    assert grammar.fmt_date("1982-09-02") == "02.09.1982"
    assert grammar.parse_date("02.09.1982") == "1982-09-02"
    assert grammar.parse_date("02.09.1982.") == "1982-09-02"  # stray dot as in the old files
    assert grammar.parse_date("") is None
    with pytest.raises(ValueError):
        grammar.parse_date("31.02.2020")


def test_gender_forms():
    f = grammar.gender_forms("F", grammar.CANDIDATE_FORMS)
    assert f["roden"] == "родена" and f["title"] == "г-жа" and f["ru_rodilsya"] == "родилась"
    m = grammar.gender_forms("M", grammar.CANDIDATE_FORMS)
    assert m["grazhdanin"] == "гражданин" and m["title"] == "г-н"
    assert grammar.gender_forms("", grammar.CANDIDATE_FORMS)["roden"] == "роден/родена"
