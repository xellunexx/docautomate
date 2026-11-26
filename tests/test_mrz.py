import pytest

from docautomate import mrz

# ICAO Doc 9303 specimen (fictional person)
ICAO = ("P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
        "L898902C36UTO7408122F1204159ZE184226B<<<<<10")


def make_mrz(surname="IVANOV", given="PETR<SERGEEVICH", pno="AB1234567", nat="UZB", dob="850101",
             sex="M", exp="300101"):
    l1 = (f"P<{nat}{surname}<<{given}" + "<" * 44)[:44]
    personal = "<" * 14
    body = pno + mrz.check_digit(pno) + nat + dob + mrz.check_digit(dob) + sex + exp + mrz.check_digit(exp)
    pcd = "<"
    composite = (pno + mrz.check_digit(pno) + dob + mrz.check_digit(dob) + exp + mrz.check_digit(exp)
                 + personal + pcd)
    l2 = body + personal + pcd + mrz.check_digit(composite)
    assert len(l2) == 44
    return l1 + "\n" + l2


def test_icao_specimen():
    r = mrz.parse_mrz(ICAO)
    assert r.valid, r.warnings
    assert r.surname == "ERIKSSON" and r.given_names == "ANNA MARIA"
    assert r.passport_no == "L898902C3"
    assert r.nationality == "UTO"
    assert r.birth_date == "1974-08-12"
    assert r.expiry_date == "2012-04-15"
    assert r.gender == "F"
    assert r.name_lat == "Eriksson Anna Maria"


def test_generated_mrz_with_noise_around():
    text = "PASSPORT\nREPUBLIC OF UZBEKISTAN\nsome text\n" + make_mrz() + "\n"
    r = mrz.parse_mrz(text)
    assert r.valid, r.warnings
    assert r.passport_no == "AB1234567" and r.nationality == "UZB" and r.birth_date == "1985-01-01"


def test_bad_check_digit_is_reported_not_hidden():
    good = make_mrz()
    l1, l2 = good.split("\n")
    bad = l1 + "\n" + l2[:13] + "850102" + l2[19:]  # change birth date, keep old check digit
    r = mrz.parse_mrz(bad)
    assert not r.valid
    assert any("раждане" in w for w in r.warnings)


def test_no_mrz():
    r = mrz.parse_mrz("nothing here")
    assert not r.valid and r.warnings


def test_ocr_reads_synthetic_scan(tmp_path):
    if not mrz.ocr_available():
        pytest.skip("OCR not installed")
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype("DejaVuSansMono.ttf", 30)
    except OSError:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 30)
        except OSError:
            pytest.skip("no monospace font")
    img = Image.new("RGB", (1500, 600), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 60), "PASSPORT  REPUBLIC OF UZBEKISTAN", fill="black", font=font)
    l1, l2 = make_mrz().split("\n")
    d.text((40, 440), l1, fill="black", font=font)
    d.text((40, 495), l2, fill="black", font=font)
    p = tmp_path / "scan.png"
    img.save(p)
    r = mrz.read_mrz_from_file(p)
    assert r.valid, (r.raw, r.warnings)
    assert r.passport_no == "AB1234567" and r.gender == "M"


def test_second_line_without_filler():
    l1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<"
    l2 = "L898902C36UTO7408122F1204159ZE184226B1234508"
    pno, dob, exp, personal = l2[0:10], l2[13:20], l2[21:28], l2[28:42]
    l2 = l2[:42] + mrz.check_digit(personal) + mrz.check_digit(pno + dob + exp + personal + mrz.check_digit(personal))
    r = mrz.parse_mrz(l1 + "\n" + l2)
    assert r.found and r.valid, r.warnings


def test_detected_mrz_beats_no_mrz(monkeypatch, tmp_path):
    good = make_mrz()
    l1, l2 = good.split("\n")
    broken = l1 + "\n" + l2[:13] + "850102" + l2[19:]
    monkeypatch.setattr(mrz, "ocr_passes", lambda p: ["no mrz here", broken])
    r = mrz.read_mrz_from_file(tmp_path / "x.png")
    assert r.found and r.passport_no == "AB1234567"


def test_long_heading_is_not_taken_as_line_one():
    text = "PASSPORT UNITED KINGDOM OF GREAT BRITAIN AND NORTHERN IRELAND\n" + make_mrz() + "\n"
    r = mrz.parse_mrz(text)
    assert r.passport_no == "AB1234567" and r.valid, r.warnings
