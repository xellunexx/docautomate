import zipfile
from pathlib import Path

import docx
import pytest

from docautomate import render
from docautomate.context import sample_context

MASTERS = sorted((Path(__file__).resolve().parent.parent / "masters").glob("*.docx"))


def _text(path):
    d = docx.Document(str(path))
    out = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            for c in row.cells:
                out += [p.text for p in c.paragraphs]
    return "\n".join(out)


def _make(tmp_path, *paras):
    d = docx.Document()
    for p in paras:
        d.add_paragraph(p)
    path = tmp_path / "t.docx"
    d.save(path)
    return path


@pytest.mark.parametrize("path", MASTERS, ids=lambda p: p.name)
def test_masters_are_valid_and_fill_completely(path, tmp_path):
    check = render.check_template(path)
    assert check.ok, (check.errors, check.unknown)
    out = render.fill_docx(path, sample_context(), tmp_path / "out.docx")
    xml = zipfile.ZipFile(out).read("word/document.xml").decode("utf-8")
    assert "{{" not in xml and "{%" not in xml
    text = _text(out)
    assert "ПРИМЕР ЕООД" in text or "Иванов" in text


def _master_text(path):
    import re
    with zipfile.ZipFile(path) as z:
        xml = "".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.startswith("word/"))
    return re.sub(r"<[^>]+>", "", xml).replace("\xa0", " ")


def test_masters_hold_no_personal_data_patterns():
    """No ЕГН/ЕИК/passport-like numbers or e-mails left in the shipped masters."""
    import re
    for path in MASTERS:
        text = _master_text(path)
        assert not re.search(r"\b\d{10}\b", text), path.name             # ЕГН / phone
        assert not re.search(r"\b\d{3} ?\d{3} ?\d{3}\b", text), path.name  # ЕИК
        assert not re.search(r"\b[A-Z]{2}\d{7}\b", text), path.name       # passport no.
        assert not re.search(r"[\w.]+@[\w.]+", text), path.name           # e-mail


def test_masters_hold_no_known_names():
    """Optional: DOCAUTOMATE_PII_FILE points to a local (never committed) list of real values, one per line."""
    import os
    f = os.environ.get("DOCAUTOMATE_PII_FILE")
    if not f:
        pytest.skip("DOCAUTOMATE_PII_FILE not set")
    banned = [ln.strip() for ln in open(f, encoding="utf-8") if ln.strip()]
    for path in MASTERS:
        text = _master_text(path)
        assert not [b for b in banned if b in text], path.name


def test_contract_uses_grammar_and_russian_forms(tmp_path):
    out = render.fill_docx(next(p for p in MASTERS if p.name == "trudov-dogovor-bg-ru.docx"), sample_context(), tmp_path / "td.docx")
    t = _text(out)
    assert "гражданин на Република Узбекистан, роден на 01.01.1985" in t
    assert "гражданин Республики Узбекистан, родился 01.01.1985" in t
    assert "6 /шест/ месеца" in t and "6 /шесть/ месяцев" in t
    assert "36 месеца" in t and "36 месяцев" in t
    assert "1077.00 евро" in t
    assert "Георги Иванов Петров в качеството му на управител" in t


def test_dh_lists_become_paragraphs(tmp_path):
    out = render.fill_docx(next(p for p in MASTERS if "harakteristika" in p.name), sample_context(), tmp_path / "dh.docx")
    paras = [p.text for p in docx.Document(str(out)).paragraphs]
    i = paras.index("Едно")
    assert paras[i + 1] == "Две"  # one paragraph per duty


def test_unknown_placeholder_is_rejected(tmp_path):
    c = render.check_template(_make(tmp_path, "Име: {{ candidate.nmae_cyr }}", "{{ foo }}"))
    assert not c.ok
    assert "candidate.nmae_cyr" in c.unknown and "foo" in c.unknown


def test_broken_tag_is_rejected(tmp_path):
    c = render.check_template(_make(tmp_path, "Име: {{ candidate.name_cyr }"))
    assert not c.ok and c.errors


def test_tag_split_across_runs_still_works(tmp_path):
    d = docx.Document()
    p = d.add_paragraph("Име: ")
    for part in ("{{ cand", "idate.na", "me_cyr }}"):
        r = p.add_run(part)
        r.bold = part.startswith("idate")
    path = tmp_path / "split.docx"
    d.save(path)
    c = render.check_template(path)
    assert c.ok and c.used == {"candidate.name_cyr"}
    out = render.fill_docx(path, sample_context(), tmp_path / "o.docx")
    assert "Иванов Петър Сергеевич" in _text(out)


def test_special_characters_are_escaped(tmp_path):
    ctx = sample_context()
    ctx["employer"]["name"] = "А & Б <ООД>"
    out = render.fill_docx(_make(tmp_path, "{{ employer.name }}"), ctx, tmp_path / "o.docx")
    assert "А & Б <ООД>" in _text(out)


def test_not_a_docx(tmp_path):
    p = tmp_path / "x.docx"
    p.write_text("hello")
    c = render.check_template(p)
    assert not c.ok and "Word" in c.errors[0]


def test_sandbox_blocks_code_execution(tmp_path):
    payload = "{% set c = cycler %}{{ c.__init__.__globals__.os.system('echo hacked') }}"
    c = render.check_template(_make(tmp_path, payload))
    assert not c.ok


def test_loop_variable_is_allowed_only_inside_for(tmp_path):
    ok = render.check_template(_make(tmp_path, "{% for x in position.dh_duties %}{{ loop.index }}. {{ x }}{% endfor %}"))
    assert ok.ok, (ok.errors, ok.unknown)
    bad = render.check_template(_make(tmp_path, "{{ loop.index }}"))
    assert not bad.ok and "loop" in bad.unknown


def test_fill_itself_is_sandboxed(tmp_path):
    # bypasses check_template, so this fails if the sandbox is ever removed from _jinja_env
    from jinja2.sandbox import SecurityError
    marker = tmp_path / "hacked.txt"
    payload = ("{% set c = cycler %}{{ c.__init__.__globals__.os.system('echo x > "
               + marker.as_posix() + "') }}")
    with pytest.raises(SecurityError):
        render.fill_docx(_make(tmp_path, payload), sample_context(), tmp_path / "out.docx")
    assert not marker.exists()
