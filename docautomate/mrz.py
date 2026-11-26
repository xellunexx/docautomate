"""Passport MRZ (ICAO 9303 TD3: two lines of 44 characters) reading and parsing.

parse_mrz() is pure and works on text. read_mrz_from_file() runs OCR when the optional
OCR package is installed. The result is always a *suggestion*: the operator checks and
corrects it on the form before saving.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path

_WEIGHTS = (7, 3, 1)


def _char_value(c: str) -> int:
    if c.isdigit():
        return int(c)
    if "A" <= c <= "Z":
        return ord(c) - 55
    return 0  # '<'


def check_digit(data: str) -> str:
    return str(sum(_char_value(c) * _WEIGHTS[i % 3] for i, c in enumerate(data)) % 10)


@dataclass
class MrzResult:
    surname: str = ""
    given_names: str = ""
    passport_no: str = ""
    nationality: str = ""       # ISO3
    issuing_country: str = ""   # ISO3
    birth_date: str | None = None   # ISO
    expiry_date: str | None = None  # ISO
    gender: str = ""            # M / F / ''
    valid: bool = False         # all check digits passed
    warnings: list[str] = field(default_factory=list)
    raw: str = ""

    @property
    def name_lat(self) -> str:
        return " ".join(x for x in (self.surname, self.given_names) if x).title()


def _fix_digits(s: str) -> str:
    """OCR often confuses letters/digits in numeric fields."""
    return s.translate(str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1",
                                      "Z": "2", "S": "5", "B": "8", "G": "6"}))


def _date(yymmdd: str, is_expiry: bool) -> str | None:
    if not re.fullmatch(r"\d{6}", yymmdd):
        return None
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:])
    this = _dt.date.today().year % 100
    if is_expiry:
        year = 2000 + yy
    else:
        year = 1900 + yy if yy > this else 2000 + yy
    try:
        return _dt.date(year, mm, dd).isoformat()
    except ValueError:
        return None


def _normalise_lines(text: str) -> list[str]:
    lines = []
    for raw in text.upper().splitlines():
        s = re.sub(r"\s+", "", raw).replace("«", "<").replace("‹", "<")
        s = re.sub(r"[^A-Z0-9<]", "", s)
        if len(s) >= 30 and "<" in s:
            lines.append(s)
    return lines


def find_mrz_lines(text: str) -> tuple[str, str] | None:
    lines = _normalise_lines(text)
    for i, line in enumerate(lines):
        if line.startswith("P") and i + 1 < len(lines):
            l1 = (line + "<" * 44)[:44]
            l2 = (lines[i + 1] + "<" * 44)[:44]
            return l1, l2
    if len(lines) >= 2:
        return (lines[-2] + "<" * 44)[:44], (lines[-1] + "<" * 44)[:44]
    return None


def parse_mrz(text: str) -> MrzResult:
    found = find_mrz_lines(text)
    if not found:
        return MrzResult(warnings=["Не е намерена MRZ зона (двата реда с <<< в долната част на паспорта)."],
                         raw=text)
    l1, l2 = found
    res = MrzResult(raw=f"{l1}\n{l2}")
    res.issuing_country = l1[2:5].replace("<", "")
    names = l1[5:].rstrip("<")
    surname, _, given = names.partition("<<")
    res.surname = surname.replace("<", " ").strip()
    res.given_names = given.replace("<", " ").strip()

    pno, pno_cd = l2[0:9], l2[9]
    nat = l2[10:13]
    dob, dob_cd = _fix_digits(l2[13:19]), _fix_digits(l2[19])
    sex = l2[20]
    exp, exp_cd = _fix_digits(l2[21:27]), _fix_digits(l2[27])
    personal, personal_cd = l2[28:42], l2[42]
    final_cd = _fix_digits(l2[43])

    res.passport_no = pno.replace("<", "")
    res.nationality = nat.replace("<", "")
    res.birth_date = _date(dob, is_expiry=False)
    res.expiry_date = _date(exp, is_expiry=True)
    res.gender = sex if sex in ("M", "F") else ""

    checks = [
        ("номер на паспорта", pno, pno_cd),
        ("дата на раждане", dob, dob_cd),
        ("валидност", exp, exp_cd),
    ]
    if personal_cd != "<" or personal.strip("<"):
        checks.append(("личен номер", personal, personal_cd))
    composite = pno + pno_cd + dob + dob_cd + exp + exp_cd + personal + personal_cd
    checks.append(("общата контролна цифра", composite, final_cd))

    ok = True
    for label, data, cd in checks:
        if check_digit(data) != cd:
            ok = False
            res.warnings.append(f"Контролната цифра за {label} не съвпада – проверете ръчно.")
    if res.birth_date is None:
        res.warnings.append("Датата на раждане не е разчетена.")
    if res.expiry_date is None:
        res.warnings.append("Датата на валидност не е разчетена.")
    res.valid = ok and res.birth_date is not None and res.expiry_date is not None
    return res


# ---------------------------------------------------------------- OCR

_ocr_engine = None


def ocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def _image_from_file(path: Path):
    from PIL import Image
    if path.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(path))
        try:
            return pdf[0].render(scale=300 / 72).to_pil().convert("RGB")
        finally:
            pdf.close()
    return Image.open(path).convert("RGB")


def ocr_passes(path: Path) -> list[str]:
    """OCR the whole page, then the bottom third enlarged (where the MRZ is)."""
    global _ocr_engine
    if not ocr_available():
        raise RuntimeError("Модулът за разчитане (OCR) не е инсталиран. Въведете данните ръчно.")
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
    if _ocr_engine is None:
        _ocr_engine = RapidOCR()
    img = _image_from_file(path)
    texts = []
    for candidate in (img, _bottom(img)):
        result, _ = _ocr_engine(np.array(candidate))
        if result:
            # sort boxes top->bottom so MRZ line 1 comes before line 2
            result.sort(key=lambda r: (r[0][0][1], r[0][0][0]))
            texts.append("\n".join(r[1] for r in result))
    return texts


def _bottom(img):
    w, h = img.size
    crop = img.crop((0, int(h * 0.6), w, h))
    if crop.width < 1600:
        f = 1600 / crop.width
        crop = crop.resize((int(crop.width * f), int(crop.height * f)))
    return crop


def read_mrz_from_file(path: Path) -> MrzResult:
    """Try each OCR pass; return the first whose check digits pass, else the one with fewest warnings."""
    results = [parse_mrz(t) for t in ocr_passes(path)]
    if not results:
        return MrzResult(warnings=["Не е разчетен текст от изображението."])
    for r in results:
        if r.valid:
            return r
    return min(results, key=lambda r: len(r.warnings))
