# Templates inventory

Source: `C:\lab\docautomate` on Xel's PC (read only, 2026-11-26). Read via text extraction plus a check of each file's internal structure.

## Headline

- The folder holds **6 Word documents and 1 phone screenshot**, not 15 templates.
- The 6 documents are **already filled in** for one real case (candidate A, employer X). They are not blank templates. No file has form fields, content controls or `{{placeholders}}`.
- Together they are the document pack for one **Single Permit for residence and work (Единно разрешение за пребиваване и работа, ЗЧРБ чл. 24и)** application to the Migration Directorate.
- The filled files already contain **two copy-paste errors from earlier cases**, which is the strongest argument for the app (see "Errors found").

## Per document

| # | File | Format | What it is | Varies per |
|---|------|--------|------------|-----------|
| 1 | `Заявление-….doc` | Word 97-2003 .doc, 5 pages | Official MoI form, Приложение № 3а към чл. 60, ал. 1 ППЗЧРБ: application for prolonged residence (bilingual BG/EN), with checkbox grounds (24и, 24к, 33к…) | candidate + employer + position |
| 2 | `ТД-… -2.doc` | Word .doc, 5 pages | Employment contract (трудов договор), Bulgarian + Russian versions in one file | candidate + employer + position + terms |
| 3 | `Контролен лист ….docx` | .docx, 1 table | Migration Directorate checklist of documents for the Single Permit (15 numbered items, ✓/✗/Н/П column) | candidate + employer (header only); body is fixed |
| 4 | `Обосновка-….docx` | .docx | Employer's justification for hiring a third-country national (обосновка на искането) | employer + position + site; long free prose |
| 5 | `ДХ - ….docx` | .docx | Job description (длъжностна характеристика) | employer + position + site; long free prose |
| 6 | `Условия за труд-….docx` | .docx | Employer declaration under чл. 7, ал. 1, т. 2 ЗТМТМ that pay and conditions are not worse than for Bulgarians | employer + candidate name |
| 7 | `WhatsApp Image 2026-11-26….jpeg` | Screenshot | A ChatGPT mock-up of a "candidate profile for employer" card (skills, availability, interview/document status, "Оценка от Staff Consulting", video QR). Labelled illustrative, not a template | n/a, idea for a future output |

### Fields per document

**1. Заявление (Приложение 3а)**
- Directorate addressed (ДО Директора на …) — blank
- Candidate: full name Latin (as in passport), full name Cyrillic, date of birth, place of birth (city/region), country of birth, citizenship, passport number, passport issued by, passport valid until
- Candidate address in Bulgaria (town, district) — blank; contact phone
- ЛНЧ — blank; date of entry, border point, visa type, visa period, visa purpose — blank
- Marital status — blank; period of residence (3 години)
- Employer: name, ЕИК, registered address, representative (blank), phone, e-mail, number of staff, number of foreign staff
- "For the employed foreigner under contract" — candidate name (see errors)
- Place of work address
- Education, specialty, qualification — blank
- Position + НКПД code, occupational class (неквалифицирани работници), contract extension (Да/Не), contract duration
- Ground checkbox (24и ticked for this case)
- Additional info, enclosed documents list — mostly blank
- Delivery method: e-mail address for notifications (an agency address, which looks like the agency's, not the employer's)
- Date, signatures — blank (signed by hand)

**2. Трудов договор (BG + RU)**
- Contract number and date, city of signing — blank
- Employer: name, registered address, ЕИК, representative full name and role
- Candidate: names Cyrillic/Latin, citizenship, date and place of birth, passport number, issue date, issuing country
- Position + НКПД code; place of work address
- Term (36 месеца); probation (6 месеца)
- Working time regime (пълно работно време, СИРВ)
- Monthly gross salary (620.20 евро), pay day
- Paid annual leave days (20)
- Housing, medical insurance, travel cost clauses (fixed text for now, could vary by employer)
- Notice period (3 месеца)
- Start date — blank
- All of the above repeated in Russian, with **Russian forms of the citizenship and verbs** ("гражданин Республики Узбекистан, родился …")

**3. Контролен лист**
- Application reg. № — blank
- Employer name + ЕИК
- Candidate names Cyrillic/Latin, ЛНЧ (blank), passport number
- Per-item "Н/П" marks (items 6, 7, 12–15 marked Н/П in this case) — depends on case type
- Place, date, signatures — blank

**4. Обосновка**
- Employer name, ЕИК, address, representative full name + ЕГН
- Purpose (Одобрение на Единно разрешение…)
- Candidate names Cyrillic/Latin, citizenship, DOB, place of birth, passport no., issue date, validity date
- Position + НКПД code, place of work
- **Free prose**: description of the employer's site/business, why the role is needed, labour market search, candidate suitability. About 5 paragraphs, written per employer and per position
- Representative name under signature

**5. Длъжностна характеристика**
- Employer name + ЕИК; position; НКПД code; place of work; reporting line
- **Free prose**: purpose, ~13 duties, ~9 responsibilities, rights, requirements, working conditions. Per position (reusable across candidates in the same position)
- Signature names: representative, candidate

**6. Декларация за условия на труд**
- Representative full name + ЕГН and role; employer name, ЕИК, address
- Candidate full name Cyrillic with title (г-н / г-жа)
- Date, city, signature — blank

## Merged field list

### Candidate (per person)
| Field | Used in | Notes |
|---|---|---|
| Full name, Latin (as passport) | 1, 2, 3, 4 | |
| Full name, Cyrillic | 1–6 | Transliteration is a human decision, store it, don't auto-generate |
| Gender / title (г-н, г-жа; роден/родена; гражданин/гражданка) | 2, 4, 6 | Needed for Bulgarian and Russian grammar agreement |
| Date of birth | 1, 2, 4 | Format `02.09.1982` |
| Place of birth | 1, 2, 4 | Kept in Latin as in passport ("Khorezm Region") |
| Country of birth | 1 | |
| Citizenship | 1, 2, 4 | Needs BG nominative ("Република Узбекистан") and RU genitive ("Республики Узбекистан") |
| Passport number | 1, 2, 3, 4 | |
| Passport issue date | 2, 4 | |
| Passport valid until | 1, 4 | |
| Passport issued by | 1, 2 | |
| Phone | 1 | |
| ЛНЧ | 1, 3 | Blank at first application, known on renewal |
| Address in Bulgaria | 1 | Blank in this case |
| Entry date, border point, visa type/period/purpose | 1 | Blank in this case |
| Marital status | 1 | Blank in this case |
| Education, specialty, qualification | 1 | Blank in this case |

### Employer (entered once)
| Field | Used in |
|---|---|
| Company name (with legal form, e.g. ЕООД) | 1–6 |
| ЕИК | 1–6 (written as `119 595 538` and `119595538`, pick one) |
| Registered address (седалище и адрес на управление) | 1, 2, 4, 6 |
| Representative full name | 2, 4, 5, 6 |
| Representative role (управител) | 2, 4, 6 |
| Representative ЕГН | 4, 6 (sensitive) |
| Representative gender (в качеството си/му) | 2, 6 |
| Phone, e-mail | 1 |
| Staff count, foreign staff count | 1 (changes over time) |

### Position / job site (per employer, reusable across candidates)
| Field | Used in |
|---|---|
| Job title | 1–5 |
| НКПД code | 1–5 |
| Occupational class | 1 |
| Place of work address | 1, 2, 4, 5 |
| Reporting line | 5 |
| Site/business description, need for hire, labour market search (prose) | 4 |
| Duties, responsibilities, rights, requirements, conditions (prose) | 5 |

### Case / contract (per application)
| Field | Used in |
|---|---|
| Application type / legal ground (24и, 24к, 33к…) | 1, 3 (and which checklist items are Н/П) |
| Extension of contract (Да/Не) | 1 |
| Contract term (36 месеца / 3 години) | 1, 2 |
| Probation period | 2 |
| Salary and currency | 2 |
| Pay day, leave days, working time regime, notice period | 2 |
| Housing / insurance / travel clauses | 2 |
| Contract number, date, city, start date | 2 (filled by hand today) |
| Directorate addressed | 1 |
| Notification e-mail | 1 |
| Document date, city | 2, 4, 5, 6 |

## Hard to fill automatically

1. **Prose in Обосновка and ДХ.** These are written per employer and position. The app should store them on the Position record (write once, reuse), or offer a library of standard texts per job type. Generating new prose per candidate is not needed.
2. **Grammar agreement.** Gender changes Bulgarian and Russian words (роден/родена, гражданин/гражданка, г-н/г-жа, в качеството си/му). The contract also needs the Russian case form of the citizenship. Needs a gender field and either conditional text in templates or small lookup tables.
3. **Russian half of the contract.** Every candidate value appears twice; country names need Russian forms.
4. **Cyrillic transliteration of names.** Not deterministic; store what the operator types.
5. **Checkboxes and Н/П marks.** The 3а form's grounds and the checklist's Н/П column depend on the case type. Needs conditional logic in the template.
6. **Official form layout.** Приложение 3а is a government form. Its layout must be kept exactly; if MoI publishes a new version, the template must be replaced.
7. **Number formats.** ЕИК written with and without spaces, dates as `02.09.1982.` with a stray dot, salary as `620.20 евро`. Pick formats once in the app.
8. **Values that change over time** (employer staff counts, foreign staff count) must be asked for per application, not stored once.
9. **Signatures and stamps** stay manual, so the PDFs are printed and signed.

## Errors found in the filled files

- **Заявление**, field "For the employed foreigner under contract": shows **the name of an earlier candidate**, a different person, left over from an earlier case.
- **Трудов договор (BG)**: the representative is written **the representative name plus a stray surname**. The extra word looks like a surname left over from another employer's representative. The Russian half has the name correctly.

Both are the kind of mistake that one data entry feeding every template removes.

## Fit for approach A (staff upload Word files with `{{placeholder}}` tags)

- **Good fit overall.** All six are plain Word text with no form fields or content controls, so staff can open a filled copy and replace values with tags like `{{candidate.name_cyr}}`.
- **Convert the two .doc files to .docx first** (Заявление and ТД). Template libraries such as docxtpl only read .docx.
- **Word splits text into many small formatting runs** (over 1,000 in ДХ). A tag typed in one go is usually fine, but a tag edited afterwards can be split and fail silently. The upload step should check every tag and list unknown or broken tags before saving.
- **Needs more than plain substitution:** conditionals for gender and case type, and the checkbox glyphs. Jinja-style `{% if %}` in docxtpl covers this, but office staff will need a short tag cheat sheet and a preview button.
- **Output to PDF** needs a converter (LibreOffice headless works for these files; it converted all six cleanly here).
- **Prose sections** should become a single tag each (`{{position.justification}}`, `{{position.duties}}`), with the text stored on the Position record.

## Case-type folders (added 2026-11-26, 14:43 UTC)

Xel added three folders, one per case type, downloaded from Google Drive:

| Case type | Folder | Contents as of 14:50 UTC |
|---|---|---|
| 3-year visa (Single Permit, the case above) | `БЛАНКИ - 3 годишна виза…\БЛАНКИ - 3 годишна виза` | 4 files: Заявление, Контролен лист, ТД, Условия за труд |
| 3-month visa | `БЛАНКИ - 3 месечна виза…\БЛАНКИ - 3 месечна виза` | **empty** |
| Extension (удължаване) | `БЛАНКИ - Удължаване…\БЛАНКИ - Удължаване` | **empty** |

Findings for the 3-year set:
- The "blanks" are **not blank**. All four are still named after and filled for candidate A / employer X. Text compare against the filled files in the main folder: Контролен лист, ТД and Условия за труд are word for word the same. This confirms the office copies the last case as the master.
- The only difference: in the Заявление the employer phone/e-mail line and the notification e-mail say **a different agency address** instead of an agency address. So the **notification e-mail varies by case**, probably by which agency office or partner handles the candidate. It becomes a per-case field (or an "agency office" record) rather than fixed text.
- The 3-year set has **no ДХ and no Обосновка**. Either they are not always required (the checklist marks the job description Н/П when it is not part of the contract), or they are kept per employer elsewhere. Needs Xel's confirmation.
- A new file `ассаасдса.txt` in the main folder is notes for a different project (a contracts dashboard), not a template. Ignored.

So far the template set per case type is:

| Template | 3-year visa | 3-month visa | Extension |
|---|---|---|---|
| Заявление (Прил. 3а) | ✓ | ? | ? |
| Контролен лист | ✓ | ? | ? |
| Трудов договор BG/RU | ✓ | ? | ? |
| Декларация условия на труд | ✓ | ? | ? (checklist says not needed for extensions) |
| Длъжностна характеристика | ✓ | ✓ | ✓ |
| Обосновка | ✓ | ✓ | ✓ |

Xel confirmed (15:04 UTC): the обосновка and длъжностна характеристика are needed for **every** case type. The 3-month and extension templates haven't been sent to Xel yet; this inventory waits for them.

The checklist itself already hints at extension differences: education documents, the conditions declaration and the regulated-profession document are **not** submitted for an extension, and an additional agreement (допълнително споразумение) to the contract can replace the contract. Expect an extension set with an additional-agreement template.

The merged field list above still holds. Additions from the case-type folders:
- **Case type** (3-year visa / 3-month visa / extension) picks the template set and the Н/П marks.
- **Notification / contact e-mail** is per case (two values seen).

## Answers from Xel (2026-11-26)

1. The other templates are coming into `C:\lab\docautomate` soon. This inventory will be extended when they land.
2. No blank masters today. The app needs **master templates plus an option to start from a previous filled case and edit it**.
3. The Single Permit is **not** the only case type. Xel will provide the others.

Still open: is the profile card in the screenshot a planned output for employers?

## Update 2026-11-26 (evening): new folders and the задание

Xel added new downloads plus a functional specification, `Staff_Consulting_IT_Zadanie.pdf` (версия 0.12). Names of people and companies are left out here on purpose.

### What arrived

| Folder | New files | Notes |
|---|---|---|
| 3-year visa (second download) | Обосновка (filled), Декларация за условията на живеене по чл. 28, ал. 1-2 ЗТМТМ (placeholder X text), Декларация за жилище (filled), Invitation Letter (filled, English) | Заявление, Контролен лист, ТД and Условия за труд are byte-identical to the first download |
| 3-month visa | Трудов договор – 90 дни (**blank with underscores**, Bulgarian only), Декларация чл. 28 (same file as above), Условия за труд (same file as the 3-year one) | first real blank master in the whole set |
| Extension | still **empty** | |
| Вариации Обосновки | 12 filled обосновки for different employers and positions | reference for structure and style only |

### New template types

| Template | Format | Variable parts |
|---|---|---|
| **Трудов договор – 90 дни** (seasonal) | .docx, BG only, underscores for blanks | employer (name, address, ЕИК, representative + ЕГН), worker (name, DOB, ЕГН/ЛНЧ, citizenship, passport no., issue/expiry, issued by), position + НКПД, place of work, salary in figures and words. Fixed: 8 h/day, 90 days, 20 days leave, housing/insurance/transport paid by employer |
| **Декларация чл. 28 ЗТМТМ** (housing for seasonal workers) | .docx | representative + ЕГН, employer, ЕИК, address; **list of workers** (several names in one declaration); housing address; date, city |
| **Декларация за жилище** (3-year) | .docx | representative + ЕГН, employer, ЕИК, address; housing address; one worker: names cyr/lat, citizenship, DOB, place of birth, passport no., issue and expiry date |
| **Invitation Letter** | .docx, English | embassy city/country; employer (name, ЕИК, address, manager); date; worker (name, citizenship, DOB, place of birth, passport no.); position, NACE/НКПД code, profession class; term 3 years, probation 6 months; place of work; hours; salary; leave; he/him vs she/her (Mr/Ms) |
| **Обосновка** (new 3-year version) | .docx | header block as before; the prose follows the 4-paragraph order in the задание (activity, need, search for Bulgarian staff, not limiting access to the labour market) |

### Template set per visa type (from the задание, section 04)

| Document | 3 years | 3 months | Extension | Have a master? |
|---|---|---|---|---|
| Контролен лист | ✓ | – | ✓ | yes (3-year); extension version not received |
| Заявление (Прил. 3а) | ✓ | – | ✓ | yes |
| Условия на труд | ✓ | ✓ | ✓ | yes |
| Трудов договор | by country | by country | by country | BG/RU (3-year) yes; BG 90-day yes; **English version missing**; RU 90-day missing |
| Обосновка | initial hire | – | extension | yes (initial); extension prose order defined in the задание |
| Длъжностна характеристика | ✓ | ✓ | ✓ | yes |
| Декларация за жилище | ✓ | ✓ | ✓ | two forms: чл. 28 (seasonal) and the 3-year one; which goes where needs confirming |
| Invitation Letter | only India and Nepal | – | – | yes (filled sample) |
| 1-year visa | to be defined in the задание | | | |

Contract language rule: Uzbekistan and Kyrgyzstan get Russian, India, Nepal and every other country get English.

### Extension set (added 2026-11-26, 20:08 UTC, loose files in the main folder)

| File type | What it shows |
|---|---|
| Контролен лист (extension) | same MoI checklist; header has the worker's ЛНЧ; items 6, 7, 12–15 marked Н/П |
| Обосновка (extension) | prose follows the 5-step extension order from the задание (activity, continued need, worker already trained, labour market search, no restriction of access) |
| Трудов договор BG/RU, **1 year** | same contract as the 3-year one with "срок от 1 година" |
| Заявление (Прил. 3а) | same official form |

No English contract exists anywhere (folder or project library). Xel asked (20:12 UTC) to translate the existing contract: build BG/EN versions from the BG/RU contract (1 year, 3 years, extension) and from the BG 90-day contract (3 months), marked as drafts for Xel's review.
