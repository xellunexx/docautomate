"""Build the master templates added for the задание (stage 3). Run once from the app folder:

    .venv\\Scripts\\python.exe scripts\\build_masters.py

It writes into masters/. No real person's data is used: the texts come from the blank forms and the
existing BG/RU contract master; every variable part is a {{ placeholder }}.

The English and Russian contract versions are translations made by Claude for Xel to review
(the templates are named "– чернова" in the manifest until someone checks them).
"""
from __future__ import annotations

import copy
from pathlib import Path

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

ROOT = Path(__file__).resolve().parent.parent
MASTERS = ROOT / "masters"

# ----------------------------------------------------------------------------------------------
# 1. BG/EN contract (3 years, extension): same layout as the BG/RU master, English in the right
#    column. One entry per paragraph of the Russian column, in order (72 paragraphs).
# ----------------------------------------------------------------------------------------------
EN_CONTRACT = [
    "{{ employer.name }} ",
    "Employment Contract No. ......./ .................",
    "",
    "Today, {{ case.contract_date }}, in the city of {{ case.doc_city }}, between",
    "{{ employer.name }}, with registered office and address of management: {{ employer.address }}, "
    "UIC {{ employer.eik }}, represented by {{ employer.rep_name }} in the capacity of {{ employer.rep_role }}, "
    "hereinafter referred to as the EMPLOYER, and",
    "{{ candidate.names }}, citizen of the {{ candidate.citizenship_en }}, born on {{ candidate.birth_date }} "
    "in {{ candidate.birth_place }}, under passport No. {{ candidate.passport_no }}, issued on "
    "{{ candidate.passport_issue_date }} by the {{ candidate.citizenship_en }}, hereinafter referred to as the EMPLOYEE",
    "On the grounds of Art. 68, para. 1, item 1 and Art. 70, para. 1 of the Labour Code and Art. 24i, para. 1 "
    "of the Foreigners in the Republic of Bulgaria Act, the present employment contract was concluded",
    "",
    "1. Subject and term of the contract",
    "Art. 1.1 The EMPLOYER assigns and the EMPLOYEE accepts to perform the position of "
    "“{{ position.title }}”, NCOP code {{ position.nkpd }}, at {{ employer.name }}",
    "1.2 The place of work is {{ position.workplace }}",
    "Art. 1.3 The contract is concluded for a term of {{ case.contract_months }} {{ case.contract_unit_en }}",
    "Art. 1.4 The probation period is {{ case.probation_months }} /{{ case.probation_words_en }}/ "
    "{{ case.probation_unit_en }}, counted from the date of starting work. The probation period is agreed in favour "
    "of the EMPLOYER. If the EMPLOYER does not terminate the contract under Art. 71, para. 1 of the Labour Code before "
    "the end of the probation period, the contract shall be deemed finally concluded for a fixed term under Art. 68, "
    "para. 1, item 1 of the Labour Code",
    "Art. 1.5 This contract enters into force after the foreigner receives a residence document for the territory of "
    "the Republic of Bulgaria from the Ministry of Interior, under Art. 24i, para. 1 of the Foreigners in the Republic "
    "of Bulgaria Act",
    "",
    "2. Working time and leave",
    "Art. 2.1 The EMPLOYEE shall work full time on a shift schedule under summarised calculation of working time",
    "Art. 2.2 The basic monthly salary of the EMPLOYEE is {{ case.salary }} {{ case.currency }}, paid by the "
    "{{ case.pay_day }} day of the month following the month for which it is due",
    "Art. 2.3 The EMPLOYEE may receive additional pay for overtime, night work, work on public holidays or under "
    "adverse working conditions in accordance with the legislation of the Republic of Bulgaria",
    "Art. 2.4 The EMPLOYEE undertakes to start work after receiving the residence document from the Ministry of "
    "Interior",
    "Art. 2.5 The basic (extended) paid annual leave is {{ case.leave_days }} days. The EMPLOYEE is entitled to use "
    "paid leave after completing 4 /four/ months of total length of service in the Republic of Bulgaria. The "
    "additional paid annual leave is {{ case.extra_leave_days }} /{{ case.extra_leave_words_en }}/ days",
    "3. Accommodation, medical insurance, transport",
    "Art. 3.1 The EMPLOYEE is provided with suitable accommodation meeting all health and safety requirements until "
    "the end of the contract. If the EMPLOYEE refuses it, accommodation is entirely at the EMPLOYEE’s expense",
    "Art. 3.2 The EMPLOYER covers the compulsory medical insurance for the whole term of the contract. The EMPLOYER is "
    "not obliged to pay for medical treatment during the EMPLOYEE’s stay in the Republic of Bulgaria beyond what "
    "the medical insurance covers.",
    "Art. 3.3 The EMPLOYER undertakes to cover the EMPLOYEE’s travel costs from the country of permanent residence "
    "to the place of work in the Republic of Bulgaria. Travel costs back are covered by the EMPLOYER only if the "
    "EMPLOYEE completes the term of the contract",
    "4. Termination of the employment contract",
    "4.1 The employment contract terminates on the expiry of its term",
    "4.2 The notice period for early termination of the employment contract is {{ case.notice_months }} "
    "/{{ case.notice_words_en }}/ {{ case.notice_unit_en }}, but not longer than the remaining term of the contract.",
    "",
    "5. Obligations of the employee",
    "Art. 5.1 To perform the work duties accurately and in good faith.",
    "Art. 5.2 To come to work on time and strictly follow the set work schedule",
    "Art. 5.3 To come to work in a condition that allows performing the assigned tasks, and not to use alcohol or "
    "other intoxicating substances during working hours",
    "Art. 5.4 To perform the work in the required quantity and quality",
    "Art. 5.5 To observe the technical and technological rules",
    "Art. 5.6 To follow the EMPLOYER’s instructions on health and safety at work and fire safety in all cases "
    "related to the work, taking care of their own health and safety and of the health and safety of all other "
    "persons who are in or near the work premises",
    "Art. 5.7 To take good care of the property entrusted to them or used in the work, and to save raw materials, "
    "materials, energy, tools and all other means provided for the work",
    "Art. 5.8 Not to use the EMPLOYER’s equipment, premises or assets for purposes other than the work",
    "Art. 5.9 To be loyal to the EMPLOYER, not to abuse the EMPLOYER’s trust, not to disclose confidential "
    "information, and to protect the good name of the company",
    "Art. 5.10 To observe discipline and the internal rules of the company and not to prevent other workers and "
    "employees from performing their duties",
    "Art. 5.11 To observe the rules of good conduct and not to get involved in conflicts, either at work or in the "
    "accommodation provided by the EMPLOYER. In case of a breach of this article the EMPLOYER may impose the most "
    "severe disciplinary sanction – dismissal, in compliance with the Labour Code",
    "Art. 5.12 To coordinate the work with the other workers and employees and to help and assist them in accordance "
    "with the EMPLOYER’s instructions",
    "Art. 5.13 To perform all other obligations arising from a legal act, the employment contract or the nature of "
    "the work",
    "Art. 5.14 To notify the EMPLOYER immediately of any change of the current address in the Republic of Bulgaria. If "
    "the EMPLOYEE changes the address without notifying the EMPLOYER, all notices sent to the old address shall be "
    "deemed duly delivered. If nobody is found at the address or nobody there agrees to receive the item, the date of "
    "its return to the sender shall be deemed the date of receipt",
    "6. Obligations of the employer",
    "Art. 6.1 The EMPLOYER shall provide the EMPLOYEE with normal conditions for performing the agreed work, providing:",
    "6.1.1 the work agreed when the employment relationship began;",
    "6.1.2 a workplace and conditions in line with the nature of the work;",
    "6.1.3 healthy and safe working conditions;",
    "6.1.4 instructions on how to perform the work duties and exercise the labour rights, including familiarisation "
    "with the internal work rules and the health and safety rules.",
    "6.2 The EMPLOYER shall respect the dignity of the EMPLOYEE while performing the work under the employment "
    "relationship.",
    "7. Other provisions",
    "Art. 7.1 On starting work the EMPLOYER provides the EMPLOYEE with uniform clothing. The EMPLOYEE shall wear it at "
    "work, keep it in good condition and look after it as the EMPLOYER’s property. If the uniform is lost, "
    "destroyed or damaged through the EMPLOYEE’s fault, the EMPLOYEE bears financial liability under the Labour "
    "Code. On termination of the employment relationship the EMPLOYEE shall return the uniform to the EMPLOYER",
    "Art. 7.2 The EMPLOYER, as personal data controller, may process and store the EMPLOYEE’s personal data in "
    "accordance with the Personal Data Protection Act",
    "Art. 7.3 Matters not settled in this contract are governed by the Labour Code",
    "This contract was drawn up in Bulgarian and English, both having equal legal force, and signed in two identical "
    "copies – one for each party",
    "",
    "",
    "EMPLOYER:………………",
    "",
    "EMPLOYEE:……………………….   ",
    "This employment contract and the certified notification under Art. 62, para. 5 of the Labour Code were handed",
    "",
    "to the EMPLOYEE on ...............",
    "",
    "EMPLOYER:………………",
    "",
    "EMPLOYEE:……………………….   ",
    "",
    "The EMPLOYEE undertakes to start work on...................",
    "",
    "",
]


def _set_text(paragraph, text):
    """Replace a paragraph's text and keep the formatting of its first run."""
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(text)
        return
    runs[0].text = text
    for r in runs[1:]:
        r._r.getparent().remove(r._r)


def build_bg_en_contract():
    d = docx.Document(MASTERS / "trudov-dogovor-bg-ru.docx")
    cell = d.tables[0].rows[0].cells[1]
    paras = cell.paragraphs
    assert len(paras) == len(EN_CONTRACT), (len(paras), len(EN_CONTRACT))
    for p, text in zip(paras, EN_CONTRACT):
        was_heading = len(p.text.strip()) < 60
        _set_text(p, text)
        if not was_heading and p.runs:
            p.runs[0].bold = False  # long clauses: the first Russian run was a bold value, not the clause
    # the Bulgarian half names the second language
    for p in d.tables[0].rows[0].cells[0].paragraphs:
        if "на български и руски език" in p.text:
            _set_text(p, p.text.replace("на български и руски език", "на български и английски език"))
    d.save(MASTERS / "trudov-dogovor-bg-en.docx")


# ----------------------------------------------------------------------------------------------
# 2. 90-day seasonal contract (3-month visa): BG text from the blank form, with RU or EN beside it.
# ----------------------------------------------------------------------------------------------
BG_90 = [
    ("h", "ТРУДОВ ДОГОВОР"),
    ("c", "№ {{ case.contract_no }}/{{ case.contract_date }} г."),
    ("p", "Днес, {{ case.contract_date }} г., между:"),
    ("p", "1. {{ employer.name }}, с адрес и седалище на управление: {{ employer.address }}, ЕИК: {{ employer.eik }}, "
          "представлявано от {{ employer.rep_name }} – {{ employer.rep_role }}, ЕГН {{ employer.rep_egn }}, "
          "наричан за по-кратко РАБОТОДАТЕЛ, и"),
    ("p", "2. {{ candidate.names }}, {{ candidate.roden }} на {{ candidate.birth_date }} г., ЕГН/ЛНЧ "
          "{{ candidate.lnch }}, {{ candidate.grazhdanin }} на {{ candidate.citizenship }}, документ за самоличност "
          "{{ candidate.passport_no }}, издаден на {{ candidate.passport_issue_date }} г., валиден до "
          "{{ candidate.passport_expiry }} г. от {{ candidate.passport_issued_by }}, наричан за по-кратко "
          "РАБОТНИК/СЛУЖИТЕЛ, се сключи настоящият трудов договор:"),
    ("b", "ПРЕДМЕТ, СРОК НА ДОГОВОРА И МЯСТО НА РАБОТА"),
    ("p", "1. РАБОТОДАТЕЛЯТ възлага, а РАБОТНИКЪТ/СЛУЖИТЕЛЯТ приема да изпълнява длъжността {{ position.title }} с код "
          "по НКПД: {{ position.nkpd }}, със задължения, утвърдени от РАБОТОДАТЕЛЯ в длъжностната характеристика, "
          "представляваща неразделна част от настоящия договор."),
    ("p", "2. Месторабота: {{ position.workplace }}."),
    ("p", "3. Работното време се определя на 8 (осем) часа/дневно или 40 часа/седмично при сумирано изчисляване на "
          "работното време."),
    ("p", "4. Трудовият договор се сключва за определен срок от 90 дни и със срок за изпитване в полза на "
          "работодателя, който изтича със срока на трудовия договор."),
    ("p", "5. Трудовият договор се счита за окончателно сключен и влизащ в сила след регистрация на заетостта в АЗ и "
          "влизане на РАБОТНИКА/СЛУЖИТЕЛЯ на територията на Р България."),
    ("b", "ВЪЗНАГРАЖДЕНИЕ"),
    ("p", "6. РАБОТНИКЪТ/СЛУЖИТЕЛЯТ получава следните възнаграждения:"),
    ("p", "6.1. Основно месечно трудово възнаграждение в размер на {{ case.salary }} {{ case.currency }}."),
    ("p", "6.2. Допълнително възнаграждение за придобит трудов стаж и професионален опит 0.6% за всяка година трудов "
          "стаж при настоящия работодател и за всяка година трудов стаж на същата, сходна или със същия характер "
          "работа, длъжност или професия."),
    ("p", "6.3. Други специфични допълнителни възнаграждения, изчислявани по реда, определен от вътрешните "
          "нормативни актове на РАБОТОДАТЕЛЯ."),
    ("p", "6.4. Възнагражденията се изплащат ежемесечно, до края на месеца, следващ месеца, за който се отнасят."),
    ("b", "ОТПУСКИ"),
    ("p", "7. РАБОТНИКЪТ/СЛУЖИТЕЛЯТ има право на следните отпуски:"),
    ("p", "7.1. Основен платен годишен отпуск по чл. 155 КТ – {{ case.leave_days }} работни дни, пропорционално на "
          "отработеното време."),
    ("b", "ПРЕКРАТЯВАНЕ"),
    ("p", "8. Договорът се прекратява при условията, предвидени в КТ. Когато е отправено предизвестие по чл. 326, "
          "ал. 1 или чл. 328, ал. 1 от КТ, срокът на предизвестието е 1 /един/ месец, но не повече от остатъка от "
          "срока на договора."),
    ("p", "9. За неуредени въпроси в настоящия трудов договор се прилагат разпоредбите на Кодекса на труда и "
          "нормативните актове на българското законодателство."),
    ("b", "ДРУГИ УСЛОВИЯ"),
    ("p", "10. При изпълнение на настоящия договор РАБОТОДАТЕЛЯТ се ангажира да предостави на РАБОТНИКА/СЛУЖИТЕЛЯ "
          "настаняване, осигурено и заплатено от РАБОТОДАТЕЛЯ."),
    ("p", "11. РАБОТОДАТЕЛЯТ поема за своя сметка стойността на медицинската застраховка, която осигурява "
          "медицинското лечение по време на престоя на РАБОТНИКА/СЛУЖИТЕЛЯ в Р България."),
    ("p", "12. РАБОТОДАТЕЛЯТ поема за своя сметка и другите застраховки, когато такива се изискват съгласно "
          "действащото законодателство."),
    ("p", "13. РАБОТОДАТЕЛЯТ поема за своя сметка и транспортните разходи по най-икономичния маршрут от мястото на "
          "произход на сезонния работник до работното му място в Р България и разноските в обратна посока, "
          "независимо от причините за прекратяване на договора."),
    ("p", "Настоящият трудов договор се сключва в два еднообразни екземпляра, по един за всяка страна."),
    ("s", "РАБОТОДАТЕЛ: .......................\n/подпис и печат/"),
    ("s", "РАБОТНИК (СЛУЖИТЕЛ): ......................"),
]

RU_90 = [
    "ТРУДОВОЙ ДОГОВОР",
    "№ {{ case.contract_no }}/{{ case.contract_date }} г.",
    "Сегодня, {{ case.contract_date }} г., между:",
    "1. {{ employer.name }}, с адресом и местонахождением управления: {{ employer.address }}, ЕИК: {{ employer.eik }}, "
    "в лице {{ employer.rep_name }} – {{ employer.rep_role }}, ЕГН {{ employer.rep_egn }}, далее РАБОТОДАТЕЛЬ, и",
    "2. {{ candidate.names }}, {{ candidate.ru_rodilsya }} {{ candidate.birth_date }} г., ЕГН/ЛНЧ {{ candidate.lnch }}, "
    "{{ candidate.ru_grazhdanin }} {{ candidate.citizenship_ru_gen }}, документ, удостоверяющий личность, "
    "{{ candidate.passport_no }}, выдан {{ candidate.passport_issue_date }} г., действителен до "
    "{{ candidate.passport_expiry }} г., выдан {{ candidate.citizenship_ru_instr }}, далее РАБОТНИК, заключили "
    "настоящий трудовой договор:",
    "ПРЕДМЕТ, СРОК ДОГОВОРА И МЕСТО РАБОТЫ",
    "1. РАБОТОДАТЕЛЬ поручает, а РАБОТНИК принимает выполнять должность {{ position.title_ru }}, код по НКПД: "
    "{{ position.nkpd }}, с обязанностями, утверждёнными РАБОТОДАТЕЛЕМ в должностной инструкции, которая является "
    "неотъемлемой частью настоящего договора.",
    "2. Место работы: {{ position.workplace }}.",
    "3. Рабочее время – 8 (восемь) часов в день или 40 часов в неделю при суммированном учёте рабочего времени.",
    "4. Трудовой договор заключается на определённый срок 90 дней с испытательным сроком в пользу работодателя, "
    "который истекает вместе со сроком договора.",
    "5. Трудовой договор считается окончательно заключённым и вступает в силу после регистрации занятости в Агентстве "
    "по занятости и въезда РАБОТНИКА на территорию Республики Болгария.",
    "ВОЗНАГРАЖДЕНИЕ",
    "6. РАБОТНИК получает следующие вознаграждения:",
    "6.1. Основная месячная заработная плата в размере {{ case.salary }} {{ case.currency }}.",
    "6.2. Дополнительное вознаграждение за трудовой стаж и профессиональный опыт – 0,6% за каждый год стажа у "
    "настоящего работодателя и за каждый год стажа на той же, сходной или аналогичной работе, должности или "
    "профессии.",
    "6.3. Другие дополнительные вознаграждения, рассчитываемые в порядке, установленном внутренними актами "
    "РАБОТОДАТЕЛЯ.",
    "6.4. Вознаграждения выплачиваются ежемесячно, до конца месяца, следующего за месяцем, к которому они относятся.",
    "ОТПУСКА",
    "7. РАБОТНИК имеет право на следующие отпуска:",
    "7.1. Основной оплачиваемый ежегодный отпуск по ст. 155 Кодекса труда – {{ case.leave_days }} рабочих дней, "
    "пропорционально отработанному времени.",
    "ПРЕКРАЩЕНИЕ",
    "8. Договор прекращается на условиях, предусмотренных Кодексом труда. При уведомлении по ст. 326, п. 1 или "
    "ст. 328, п. 1 Кодекса труда срок уведомления составляет 1 /один/ месяц, но не более оставшегося срока договора.",
    "9. По вопросам, не урегулированным настоящим договором, применяются Кодекс труда и нормативные акты "
    "законодательства Республики Болгария.",
    "ДРУГИЕ УСЛОВИЯ",
    "10. При исполнении настоящего договора РАБОТОДАТЕЛЬ обязуется предоставить РАБОТНИКУ жильё, обеспеченное и "
    "оплаченное РАБОТОДАТЕЛЕМ.",
    "11. РАБОТОДАТЕЛЬ оплачивает медицинскую страховку, обеспечивающую медицинское лечение во время пребывания "
    "РАБОТНИКА в Республике Болгария.",
    "12. РАБОТОДАТЕЛЬ оплачивает и другие страховки, если они требуются по действующему законодательству.",
    "13. РАБОТОДАТЕЛЬ оплачивает транспортные расходы по самому экономичному маршруту от места происхождения "
    "сезонного работника до места работы в Республике Болгария и обратно, независимо от причин прекращения договора.",
    "Настоящий трудовой договор составлен в двух одинаковых экземплярах, по одному для каждой стороны.",
    "РАБОТОДАТЕЛЬ: .......................\n/подпись и печать/",
    "РАБОТНИК: ......................",
]

EN_90 = [
    "EMPLOYMENT CONTRACT",
    "No. {{ case.contract_no }}/{{ case.contract_date }}",
    "Today, {{ case.contract_date }}, between:",
    "1. {{ employer.name }}, with address and registered office: {{ employer.address }}, UIC: {{ employer.eik }}, "
    "represented by {{ employer.rep_name }} – {{ employer.rep_role }}, personal No. {{ employer.rep_egn }}, "
    "hereinafter the EMPLOYER, and",
    "2. {{ candidate.names }}, born on {{ candidate.birth_date }}, personal No./LNCh {{ candidate.lnch }}, citizen of "
    "the {{ candidate.citizenship_en }}, identity document {{ candidate.passport_no }}, issued on "
    "{{ candidate.passport_issue_date }}, valid until {{ candidate.passport_expiry }}, issued by the "
    "{{ candidate.citizenship_en }}, hereinafter the EMPLOYEE, the present employment contract was concluded:",
    "SUBJECT, TERM OF THE CONTRACT AND PLACE OF WORK",
    "1. The EMPLOYER assigns and the EMPLOYEE accepts to perform the position of {{ position.title }}, NCOP code: "
    "{{ position.nkpd }}, with duties approved by the EMPLOYER in the job description, which is an integral part of "
    "this contract.",
    "2. Place of work: {{ position.workplace }}.",
    "3. Working time is 8 (eight) hours per day or 40 hours per week under summarised calculation of working time.",
    "4. The employment contract is concluded for a fixed term of 90 days with a probation period in favour of the "
    "employer, which ends with the term of the contract.",
    "5. The employment contract is deemed finally concluded and enters into force after the employment is registered "
    "with the Employment Agency and the EMPLOYEE enters the territory of the Republic of Bulgaria.",
    "REMUNERATION",
    "6. The EMPLOYEE receives the following remuneration:",
    "6.1. Basic monthly salary of {{ case.salary }} {{ case.currency }}.",
    "6.2. Additional pay for length of service and professional experience of 0.6% for each year of service with "
    "this employer and for each year of service in the same, similar or comparable work, position or profession.",
    "6.3. Other specific additional pay, calculated as set out in the EMPLOYER’s internal rules.",
    "6.4. Remuneration is paid monthly, by the end of the month following the month to which it relates.",
    "LEAVE",
    "7. The EMPLOYEE is entitled to the following leave:",
    "7.1. Basic paid annual leave under Art. 155 of the Labour Code – {{ case.leave_days }} working days, in "
    "proportion to the time worked.",
    "TERMINATION",
    "8. The contract terminates under the conditions provided in the Labour Code. When notice is given under "
    "Art. 326, para. 1 or Art. 328, para. 1 of the Labour Code, the notice period is 1 /one/ month, but not longer "
    "than the remaining term of the contract.",
    "9. Matters not settled in this contract are governed by the Labour Code and the laws of the Republic of "
    "Bulgaria.",
    "OTHER CONDITIONS",
    "10. In performing this contract the EMPLOYER undertakes to provide the EMPLOYEE with accommodation arranged and "
    "paid for by the EMPLOYER.",
    "11. The EMPLOYER pays for the medical insurance covering medical treatment during the EMPLOYEE’s stay in the "
    "Republic of Bulgaria.",
    "12. The EMPLOYER also pays for any other insurance required by the law in force.",
    "13. The EMPLOYER pays the travel costs by the most economical route from the seasonal worker’s place of "
    "origin to the place of work in the Republic of Bulgaria and back, regardless of why the contract ends.",
    "This employment contract was drawn up in two identical copies, one for each party.",
    "EMPLOYER: .......................\n/signature and stamp/",
    "EMPLOYEE: ......................",
]


def _doc(margins_cm=2.0, size=11):
    d = docx.Document()
    for s in d.sections:
        s.left_margin = s.right_margin = Cm(margins_cm)
        s.top_margin = s.bottom_margin = Cm(1.8)
    st = d.styles["Normal"]
    st.font.name = "Times New Roman"
    st.font.size = Pt(size)
    st.paragraph_format.space_after = Pt(4)
    return d


def _para(container, kind, text, size=None):
    p = container.add_paragraph()
    lines = text.split("\n")
    for i, line in enumerate(lines):
        r = p.add_run(line)
        if kind in ("h", "b"):
            r.bold = True
        if size:
            r.font.size = Pt(size)
        if i < len(lines) - 1:
            r.add_break()
    if kind in ("h", "c"):
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    else:
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    return p


def build_90_day(other, suffix):
    assert len(other) == len(BG_90), (suffix, len(other), len(BG_90))
    d = _doc(margins_cm=1.5, size=10)
    t = d.add_table(rows=1, cols=2)
    left, right = t.rows[0].cells
    left._tc.remove(left.paragraphs[0]._p)
    right._tc.remove(right.paragraphs[0]._p)
    for (kind, bg), text in zip(BG_90, other):
        _para(left, kind, bg)
        _para(right, kind, text)
    d.save(MASTERS / f"trudov-dogovor-90-{suffix}.docx")


# ----------------------------------------------------------------------------------------------
# 3. Housing declaration, one worker (3 years, extension)
# ----------------------------------------------------------------------------------------------
def build_housing_single():
    d = _doc()
    _para(d, "h", "ДЕКЛАРАЦИЯ", size=14)
    _para(d, "p", "{{ employer.rep_dolupodpisan }} {{ employer.rep_name }}, ЕГН {{ employer.rep_egn }}, "
                  "{{ employer.rep_v_kachestvoto }} на {{ employer.rep_role }} на {{ employer.name }}, ЕИК "
                  "{{ employer.eik }}, със седалище и адрес на управление: {{ employer.address }},")
    _para(d, "h", "ДЕКЛАРИРАМ:")
    _para(d, "p", "За целия период на пребиваването на долупосоченото лице ще предоставя жилище и адресна "
                  "регистрация на адрес: {{ candidate.residence_address }}")
    _para(d, "p", "{{ candidate.names }}, {{ candidate.grazhdanin }} на {{ candidate.citizenship }}, "
                  "{{ candidate.roden }} на {{ candidate.birth_date }} г. в {{ candidate.birth_place }}, съгласно "
                  "паспорт № {{ candidate.passport_no }}, издаден на {{ candidate.passport_issue_date }} г., валиден до "
                  "{{ candidate.passport_expiry }} г.")
    _para(d, "p", "Известно ми е, че за неверни данни нося отговорност по чл. 313 от НК.")
    _para(d, "p", "Настоящата декларация давам, за да послужи, където е необходимо.")
    _para(d, "p", "")
    _para(d, "p", "Дата: {{ case.doc_date }}\t\t\t\tДЕКЛАРАТОР: ……………………")
    _para(d, "p", "гр. {{ case.doc_city }}\t\t\t\t\t/{{ employer.rep_name }}/")
    d.save(MASTERS / "deklaracia-zhilishte.docx")


# ----------------------------------------------------------------------------------------------
# 4. Housing declaration for seasonal workers, чл. 28, ал. 1-2 ЗТМТМ (3-month visa)
# ----------------------------------------------------------------------------------------------
def build_housing_seasonal():
    d = _doc()
    _para(d, "h", "Д Е К Л А Р А Ц И Я", size=14)
    _para(d, "p", "{{ employer.rep_dolupodpisan }}, {{ employer.rep_name }}, ЕГН {{ employer.rep_egn }}, "
                  "{{ employer.rep_v_kachestvoto }} на {{ employer.rep_role }} и представляващ {{ employer.name }}, "
                  "ЕИК {{ employer.eik }}, със седалище и адрес на управление: {{ employer.address }}")
    _para(d, "h", "ДЕКЛАРИРАМ:")
    _para(d, "p", "Спазени са изискванията на чл. 28, ал. 1-2 от Закона за трудовата миграция и трудовата мобилност, "
                  "а именно:")
    _para(d, "p", "На сезонните работници:")
    _para(d, "p", "{%p for w in housing_workers %}")
    _para(d, "p", "- {{ w }}")
    _para(d, "p", "{%p endfor %}")
    _para(d, "p", "е осигурено подходящо, отговарящо на всички изисквания за безопасност и здраве, жилище до изтичане "
                  "на срока на договора, на адрес {{ candidate.residence_address }}.")
    _para(d, "p", "Мястото за живеене се предоставя от работодателя.")
    _para(d, "p", "За ползването на жилището работодателят е сключил договор за наем.")
    _para(d, "p", "Наемната цена на жилището се заплаща изцяло от работодателя и не се приспада от възнаграждението на "
                  "сезонния работник.")
    _para(d, "p", "За всяка промяна на обстоятелствата по т. 1-4 съм задължен да уведомя Агенция по заетостта.")
    _para(d, "p", "")
    _para(d, "p", "{{ case.doc_date }} год.\t\t\t\t\tДЕКЛАРАТОР: ...........................")
    _para(d, "p", "гр. {{ case.doc_city }}\t\t\t\t\t\t/подпис, печат/")
    d.save(MASTERS / "deklaracia-zhilishte-chl28.docx")


# ----------------------------------------------------------------------------------------------
# 5. Invitation Letter (3 years, India and Nepal) – English
# ----------------------------------------------------------------------------------------------
def build_invitation():
    d = _doc()
    _para(d, "p", "To:\nEmbassy/Consulate of the Republic of Bulgaria\n[{{ candidate.embassy }}]")
    _para(d, "p", "From:\n{{ employer.name }}\nUIC: {{ employer.eik }}\nAddress: {{ employer.address }}\n"
                  "Manager: {{ employer.rep_name }}")
    _para(d, "p", "Date: {{ case.doc_date }}")
    _para(d, "h", "Invitation for Employment")
    _para(d, "p", "We, {{ employer.name }}, duly registered at {{ employer.address }}, hereby formally invite "
                  "{{ candidate.name_lat }}, citizen of the {{ candidate.citizenship_en }}, born on "
                  "{{ candidate.birth_date }} in {{ candidate.birth_place }}, holder of passport No. "
                  "{{ candidate.passport_no }}, to work in the Republic of Bulgaria.")
    _para(d, "p", "{{ candidate.en_title }} {{ candidate.name_lat }} has concluded an Employment Contract with "
                  "{{ employer.name }} for the position of “{{ position.title }}” with NCOP code "
                  "{{ position.nkpd }}, profession class: {{ position.occupation_class }}.")
    _para(d, "p", "The employment contract is concluded for a period of {{ case.contract_words_en }} "
                  "({{ case.contract_months }}) {{ case.contract_unit_en }}, with a probation period of "
                  "{{ case.probation_words_en }} ({{ case.probation_months }}) {{ case.probation_unit_en }} in favour "
                  "of the employer, and shall enter into force after the receipt of a Single Permit for Residence and "
                  "Work in the Republic of Bulgaria.")
    _para(d, "p", "Key employment terms are as follows:")
    _para(d, "p", "Place of work: {{ position.workplace }}")
    _para(d, "p", "Working hours: Full-time – 8 hours per day")
    _para(d, "p", "Monthly remuneration: Basic gross monthly salary of {{ case.salary }} euro, plus additional "
                  "remuneration for professional experience in the amount of 0.6% per year, in accordance with "
                  "Bulgarian legislation and the internal rules of the employer.")
    _para(d, "p", "Paid annual leave: {{ case.leave_days }} working days per calendar year")
    _para(d, "p", "Accommodation: Provided and fully paid by the employer")
    _para(d, "p", "Medical insurance: Covered in accordance with Bulgarian law")
    _para(d, "p", "Social security contributions: Fully paid by the employer")
    _para(d, "p", "Transport expenses: Covered by the employer from the country of origin to Bulgaria and return upon "
                  "completion of the contract")
    _para(d, "p", "The employer undertakes to fulfil all obligations related to social security, accident insurance, "
                  "medical insurance and employment conditions in full compliance with the legislation of the "
                  "Republic of Bulgaria.")
    _para(d, "p", "We kindly request your assistance in issuing the necessary Type D Visa to {{ candidate.en_title }} "
                  "{{ candidate.name_lat }}, enabling {{ candidate.en_him }} to lawfully enter and work in the "
                  "Republic of Bulgaria.")
    _para(d, "p", "Yours faithfully,")
    _para(d, "p", "……………………\n{{ employer.rep_name }}\nManager\n{{ employer.name }}")
    d.save(MASTERS / "invitation-letter.docx")


if __name__ == "__main__":
    build_bg_en_contract()
    build_90_day(RU_90, "bg-ru")
    build_90_day(EN_90, "bg-en")
    build_housing_single()
    build_housing_seasonal()
    build_invitation()
    print("masters written to", MASTERS)
