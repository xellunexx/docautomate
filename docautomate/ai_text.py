"""Draft texts for the justification (обосновка) and the job description (ДХ) of a position.

Задание 04: the free text follows a fixed order – 4 points for the first permit (3 years),
5 points for an extension; the point on recruiting Bulgarian staff only when the employer has
confirmed it – and the job description has no experience or education requirements. With an Anthropic API key (env ANTHROPIC_API_KEY, kept only in the local .env)
the text is written by Claude; without a key, or when the call fails, it is built from
sentence templates. Either way the result only fills the form: staff read it and save.

Only position and company data are sent to the API, never a worker's personal data.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

MODEL = "claude-opus-5-5"

# The order of the justification (задание 04, „Обосновка | Последователност на свободния текст“).
# Each item: (key, short name, what the paragraph says). The recruitment point is written only when
# the employer has confirmed that it looked for Bulgarian staff.
P_ACTIVITY = ("activity", "Дейност", "Опишете основната дейност на фирмата.")
P_NEED = ("need", "Нужда", "Обяснете защо е необходим работник точно на тази длъжност и как назначаването "
                           "ще подпомогне предприятието.")
P_NEED_EXT = ("need", "Нужда", "Обяснете защо е необходим работник точно на тази длъжност и как "
                               "продължаването на заетостта ще подпомогне предприятието.")
P_TRAINED = ("trained", "Обучен служител", "Подчертайте, че служителят вече е обучен, познава работата и "
                                           "оставането му спестява обучение на нов служител.")
P_RECRUIT = ("recruit", "Търсене на български персонал", "Опишете предприетите действия за набиране на "
                                                          "български персонал и липсата на желаещи.")
P_NO_LIMIT = ("no_limit", "Без ограничаване на пазара", "Посочете, че назначаването не цели да ограничи "
                                                         "достъпа до пазара на труда на български граждани "
                                                         "или граждани на други държави членки на ЕС.")


def points(extension: bool, recruitment_confirmed: bool = True) -> list[tuple[str, str, str]]:
    order = ([P_ACTIVITY, P_NEED_EXT, P_TRAINED, P_RECRUIT, P_NO_LIMIT] if extension
             else [P_ACTIVITY, P_NEED, P_RECRUIT, P_NO_LIMIT])
    return [p for p in order if recruitment_confirmed or p is not P_RECRUIT]


DH_FIELDS = ("dh_purpose", "dh_duties", "dh_responsibilities", "dh_rights", "dh_requirements", "dh_conditions")


@dataclass
class Draft:
    fields: dict
    source: str                      # "ai" | "template"
    warnings: list = field(default_factory=list)


def api_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


def ai_available() -> bool:
    if not api_key():
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


# ------------------------------------------------------------------ facts sent to the model / templates
def _facts(pos: dict, emp: dict, hint: str) -> dict:
    return {
        "работодател": (emp.get("name") or "").strip(),
        "длъжност": (pos.get("title") or "").strip(),
        "код по НКПД": (pos.get("nkpd") or "").strip(),
        "клас професии": (pos.get("occupation_class") or "").strip(),
        "място на работа": (pos.get("workplace") or "").strip(),
        "пряко подчинение": (pos.get("reporting_line") or "").strip(),
        "бележки от служителя": (hint or "").strip(),
    }


# ------------------------------------------------------------------ template fallback
def _title(pos):
    return (pos.get("title") or "").strip() or "[длъжност]"


def _nkpd(pos):
    n = (pos.get("nkpd") or "").strip()
    return f", код по НКПД {n}" if n else ""


def _emp(emp):
    return (emp.get("name") or "").strip() or "Дружеството"


def template_obosnovka(pos: dict, emp: dict, extension: bool, recruitment_confirmed: bool = True,
                       hint: str = "") -> str:
    t, n, e = _title(pos), _nkpd(pos), _emp(emp)
    hint = " ".join((hint or "").split()).rstrip(".")
    activity = (f"Основната дейност на дружеството е: {hint}." if hint else
                "[Опишете основната дейност на фирмата: какво произвежда, строи или обслужва и къде.]")
    text = {
        "activity": f"{e} осъществява дейност, за която е необходим постоянен персонал на длъжност „{t}“{n}. "
                    + activity,
        "need": (f"Необходимостта от работник на длъжност „{t}“ продължава да съществува, тъй като обемът и "
                 "спецификата на дейността изискват поддържането на необходимия персонал. Продължаването на "
                 "заетостта ще осигури непрекъснатост на работния процес и качеството на предоставяните услуги."
                 if extension else
                 f"За нормалното протичане на дейността дружеството се нуждае от работник на длъжност „{t}“, "
                 "който да изпълнява възложените задачи своевременно и качествено. Липсата на достатъчно "
                 "персонал затруднява организацията на работата и натоварва останалите служители. Назначаването "
                 "ще подпомогне предприятието да изпълнява поетите ангажименти в срок."),
        "trained": "Служителят вече е преминал необходимото обучение и познава организацията на работа, "
                   "технологичните процеси и изискванията за качество и безопасност. Оставането му спестява "
                   "подбор, обучение и период на адаптация на нов служител.",
        "recruit": "Дружеството е търсило подходящи работници на местния и националния пазар на труда, "
                   "включително чрез Агенция по заетостта и обяви за работа, но не е намерило български "
                   "граждани, желаещи да заемат длъжността при предложените условия.",
        "no_limit": "Назначаването на гражданин на трета държава не цели да ограничи достъпа до пазара на труда "
                    "на български граждани или на граждани на други държави членки на Европейския съюз.",
    }
    return "\n".join(text[key] for key, _, _ in points(extension, recruitment_confirmed))


def template_dh(pos: dict, emp: dict) -> dict:
    t = _title(pos)
    boss = (pos.get("reporting_line") or "").strip() or "прекия ръководител"
    return {
        "dh_purpose": f"Изпълнява дейностите на длъжност „{t}“ качествено и в срок, съгласно указанията на "
                      f"{boss} и вътрешните правила на работодателя.",
        "dh_duties": "\n".join([
            f"Изпълнява основните дейности на длъжност „{t}“ според възложените задачи.",
            "Подготвя работното място, материалите и инструментите преди започване на работа.",
            "Поддържа работното място чисто и подредено.",
            "Спазва технологията и последователността на работа.",
            f"Докладва на {boss} за възникнали проблеми и неизправности.",
        ]),
        "dh_responsibilities": "\n".join([
            "Отговаря за качественото и навременно изпълнение на възложената работа.",
            "Отговаря за опазването на поверените му материали, инструменти и оборудване.",
            "Спазва правилата за безопасност и здраве при работа и противопожарна безопасност.",
            "Спазва трудовата дисциплина и работното време.",
        ]),
        "dh_rights": "\n".join([
            "Да получава трудово възнаграждение в уговорения размер и срок.",
            "Да ползва платен годишен отпуск съгласно Кодекса на труда.",
            "Да получава необходимите лични предпазни средства и работно облекло.",
            "Да бъде информиран за условията и организацията на работа.",
        ]),
        "dh_requirements": "\n".join([
            "Медицинска годност за работа на длъжността.",
            "Познаване и спазване на правилата за безопасност и здраве при работа.",
            "Отговорност, дисциплина и умение за работа в екип.",
        ]),
        "dh_conditions": "\n".join([
            "Работата се извършва на мястото на работа, определено от работодателя, при пълно работно време.",
            "Работодателят осигурява безопасни и здравословни условия на труд.",
        ]),
    }


# ------------------------------------------------------------------ Claude
_SYSTEM = (
    "Пишеш текстове на български език за документи, които български работодател подава в дирекция "
    "„Миграция“ при наемане на гражданин на трета държава (единно разрешение за пребиваване и работа). "
    "Стилът е официален, ясен и кратък, без преувеличения и без празни фрази. Не измисляй факти, които "
    "не са дадени: числа, имена, дати, договори, клиенти, сертификати. Където фактът липсва, пиши общо. "
    "Не споменавай лични данни на работника. Не използвай Markdown, номерация или водещи символи."
)


def _schema_obosnovka(n: int) -> dict:
    return {
        "type": "object",
        "properties": {"paragraphs": {"type": "array", "items": {"type": "string"},
                                      "minItems": n, "maxItems": n}},
        "required": ["paragraphs"],
        "additionalProperties": False,
    }


_SCHEMA_DH = {
    "type": "object",
    "properties": {
        "dh_purpose": {"type": "string"},
        "dh_duties": {"type": "array", "items": {"type": "string"}},
        "dh_responsibilities": {"type": "array", "items": {"type": "string"}},
        "dh_rights": {"type": "array", "items": {"type": "string"}},
        "dh_requirements": {"type": "array", "items": {"type": "string"}},
        "dh_conditions": {"type": "array", "items": {"type": "string"}},
    },
    "required": list(DH_FIELDS),
    "additionalProperties": False,
}


def _prompt_obosnovka(facts: dict, extension: bool, recruitment_confirmed: bool) -> str:
    pts = points(extension, recruitment_confirmed)
    order = "\n".join(f"{i}. {name}: {what}" for i, (_, name, what) in enumerate(pts, 1))
    kind = ("удължаване на единно разрешение (служителят вече работи при работодателя)" if extension
            else "първоначално единно разрешение за 3 години")
    return (
        f"Напиши основната част на обосновка за {kind}. Бланката вече съдържа заглавие, данни "
        "за работодателя и работника, обръщение „Г-н/г-жо Директор,“ и заключително изречение, затова "
        "не ги повтаряй.\n\n"
        f"Напиши точно {len(pts)} абзаца, по един за всяка точка, в този ред:\n{order}\n\n"
        "Всеки абзац е 2–4 изречения.\n\n"
        f"Данни (празно = няма данни):\n{json.dumps(facts, ensure_ascii=False, indent=1)}"
    )


def _prompt_dh(facts: dict) -> str:
    return (
        "Напиши съдържанието на длъжностна характеристика по разделите на бланката:\n"
        "dh_purpose – I. Основна цел на длъжността (един абзац, 1–2 изречения);\n"
        "dh_duties – II. Основни трудови задължения (6–10 точки);\n"
        "dh_responsibilities – III. Отговорности (4–6 точки);\n"
        "dh_rights – IV. Права (3–5 точки);\n"
        "dh_requirements – V. Изисквания за заемане на длъжността (2–4 точки). Без изисквания за опит, "
        "стаж, образование, квалификация, специалност или език; например медицинска годност, спазване на "
        "правилата за безопасност, лични качества;\n"
        "dh_conditions – VI. Условия на труд (1–3 абзаца).\n"
        "Всяка точка е едно изречение, без номер и без водещ символ.\n\n"
        f"Данни (празно = няма данни):\n{json.dumps(facts, ensure_ascii=False, indent=1)}"
    )


def _ask(prompt: str, schema: dict, client=None) -> dict:
    import anthropic
    client = client or anthropic.Anthropic(api_key=api_key(), timeout=120.0, max_retries=2)
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=_SYSTEM,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("AI отказа да напише текста.")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("AI текстът се отряза (твърде дълъг).")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(text)


def _clean(s) -> str:
    s = " ".join(str(s or "").split())
    return s.lstrip("-•*–— ").strip()


def _ai_reason(exc: Exception) -> str:
    try:
        import anthropic
    except ImportError:  # pragma: no cover
        return str(exc)
    if isinstance(exc, anthropic.AuthenticationError):
        return "ключът за AI не е приет (проверете ANTHROPIC_API_KEY в .env)"
    if isinstance(exc, anthropic.RateLimitError):
        return "AI е претоварен, опитайте след минута"
    if isinstance(exc, anthropic.APIConnectionError):
        return "няма връзка с AI (интернет)"
    if isinstance(exc, anthropic.APIStatusError):
        return f"грешка от AI ({exc.status_code})"
    return str(exc) or exc.__class__.__name__


def draft(kind: str, pos: dict, emp: dict, hint: str = "", client=None,
          recruitment_confirmed: bool = False) -> Draft:
    """kind: 'obosnovka' | 'obosnovka_ext' | 'dh'. Returns form field values to fill in."""
    if kind not in ("obosnovka", "obosnovka_ext", "dh"):
        raise ValueError(kind)
    extension = kind == "obosnovka_ext"
    warnings = []
    if kind != "dh" and not recruitment_confirmed:
        warnings.append("Точката за търсене на български персонал е пропусната, защото работодателят не я е "
                        "потвърдил. Ако е потвърдил, отметнете полето и напишете текста пак.")
    if not (pos.get("title") or "").strip():
        warnings.append("Попълнете „Длъжност“ – без нея текстът е много общ.")
    if client is not None or ai_available():
        facts = _facts(pos, emp, hint)
        try:
            if kind == "dh":
                data = _ask(_prompt_dh(facts), _SCHEMA_DH, client)
                fields = {"dh_purpose": _clean(data["dh_purpose"])}
                for k in DH_FIELDS[1:]:
                    fields[k] = "\n".join(x for x in (_clean(i) for i in data[k]) if x)
            else:
                n = len(points(extension, recruitment_confirmed))
                data = _ask(_prompt_obosnovka(facts, extension, recruitment_confirmed), _schema_obosnovka(n), client)
                paras = [x for x in (_clean(p) for p in data.get("paragraphs") or []) if x]
                if len(paras) != n:
                    raise RuntimeError(f"AI върна {len(paras)} абзаца вместо {n}.")
                fields = {kind: "\n".join(paras)}
            return Draft(fields, "ai", warnings)
        except Exception as exc:  # any AI failure falls back to the templates
            warnings.append(f"AI не успя ({_ai_reason(exc)}). Текстът е от готови изречения.")
    elif api_key():
        warnings.append("Пакетът за AI не е инсталиран. Пуснете start.bat отново. Текстът е от готови изречения.")
    if kind == "dh":
        return Draft(template_dh(pos, emp), "template", warnings)
    return Draft({kind: template_obosnovka(pos, emp, extension, recruitment_confirmed, hint)}, "template", warnings)


def load_dotenv(path) -> None:
    """Read KEY=VALUE lines from a local .env into os.environ (existing variables win)."""
    try:
        text = open(path, encoding="utf-8-sig").read()
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip().removeprefix("export ").strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if k and k not in os.environ:
            os.environ[k] = v
