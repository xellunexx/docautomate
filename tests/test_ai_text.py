"""Stage 6 of the задание: draft обосновка and ДХ with Claude, or from sentence templates without a key."""
import json
import os
from types import SimpleNamespace

import pytest

from docautomate import ai_text

POS = {"title": "Общ работник", "nkpd": "93299999", "occupation_class": "", "workplace": "гр. София",
       "reporting_line": "Управител", "obosnovka": "", "obosnovka_ext": ""}
EMP = {"name": "ТЕСТ ЕООД", "eik": "200000099", "rep_egn": "0000000000", "rep_name": "Иван Иванов Иванов"}


class FakeMessages:
    def __init__(self, payload, stop_reason="end_turn"):
        self.payload, self.stop_reason, self.calls = payload, stop_reason, []

    def create(self, **kw):
        self.calls.append(kw)
        if isinstance(self.payload, Exception):
            raise self.payload
        text = json.dumps(self.payload, ensure_ascii=False)
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="text", text=text)])


def fake_client(payload, stop_reason="end_turn"):
    msgs = FakeMessages(payload, stop_reason)
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs)), msgs


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_without_key_templates_follow_the_order_of_the_zadanie():
    d = ai_text.draft("obosnovka", POS, EMP, hint="строителство на жилищни сгради", recruitment_confirmed=True)
    assert d.source == "template" and not d.warnings
    paras = d.fields["obosnovka"].split("\n")
    assert len(paras) == 4
    assert "ТЕСТ ЕООД" in paras[0] and "строителство на жилищни сгради" in paras[0] and "93299999" in paras[0]
    assert "Назначаването ще подпомогне" in paras[1]
    assert "Агенция по заетостта" in paras[2] and "не цели да ограничи" in paras[3]
    ext = ai_text.draft("obosnovka_ext", POS, EMP, recruitment_confirmed=True).fields["obosnovka_ext"].split("\n")
    assert len(ext) == 5
    assert "[Опишете основната дейност" in ext[0]  # no hint: a visible gap for staff to fill
    assert "продължаването на заетостта" in ext[1].lower() or "Продължаването на заетостта" in ext[1]
    assert "обучение" in ext[2] and "Агенция по заетостта" in ext[3] and "не цели да ограничи" in ext[4]


def test_recruitment_point_only_when_employer_confirmed():
    d = ai_text.draft("obosnovka", POS, EMP)
    paras = d.fields["obosnovka"].split("\n")
    assert len(paras) == 3 and not any("Агенция по заетостта" in p for p in paras)
    assert "пропусната" in d.warnings[0]
    ext = ai_text.draft("obosnovka_ext", POS, EMP).fields["obosnovka_ext"].split("\n")
    assert len(ext) == 4


def test_template_job_description_has_no_experience_or_education():
    d = ai_text.draft("dh", POS, EMP)
    assert set(d.fields) == set(ai_text.DH_FIELDS)
    req = d.fields["dh_requirements"].lower()
    for word in ("опит", "стаж", "образование", "квалификация"):
        assert word not in req


def test_ai_obosnovka_uses_latest_model_and_sends_no_personal_data():
    client, msgs = fake_client({"paragraphs": ["Едно.", "- Две.", "Три.", "Четири."]})
    d = ai_text.draft("obosnovka", POS, EMP, hint="строителна фирма", client=client, recruitment_confirmed=True)
    assert d.source == "ai" and d.fields["obosnovka"] == "Едно.\nДве.\nТри.\nЧетири." and not d.warnings
    call = msgs.calls[0]
    assert call["model"] == "claude-opus-5-5"
    schema = call["output_config"]["format"]["schema"]["properties"]["paragraphs"]
    assert schema["minItems"] == schema["maxItems"] == 4
    prompt = call["messages"][0]["content"]
    assert "строителна фирма" in prompt and "Общ работник" in prompt
    for secret in (EMP["eik"], EMP["rep_egn"], EMP["rep_name"]):
        assert secret not in prompt


def test_ai_extension_asks_for_five_points():
    client, msgs = fake_client({"paragraphs": ["1.", "2.", "3.", "4.", "5."]})
    d = ai_text.draft("obosnovka_ext", POS, EMP, client=client, recruitment_confirmed=True)
    assert d.fields["obosnovka_ext"].count("\n") == 4
    assert msgs.calls[0]["output_config"]["format"]["schema"]["properties"]["paragraphs"]["maxItems"] == 5
    prompt = msgs.calls[0]["messages"][0]["content"]
    assert "удължаване" in prompt and "3. Обучен служител" in prompt and "5. Без ограничаване" in prompt


def test_ai_job_description_lists_become_lines():
    payload = {"dh_purpose": "Цел.", "dh_duties": ["А.", "Б."], "dh_responsibilities": ["В."],
               "dh_rights": ["Г."], "dh_requirements": ["Медицинска годност."], "dh_conditions": ["Д."]}
    client, msgs = fake_client(payload)
    d = ai_text.draft("dh", POS, EMP, client=client)
    assert d.source == "ai" and d.fields["dh_duties"] == "А.\nБ." and d.fields["dh_purpose"] == "Цел."
    assert "Без изисквания за опит" in msgs.calls[0]["messages"][0]["content"]


@pytest.mark.parametrize("payload,stop", [
    (RuntimeError("boom"), "end_turn"),
    ({"paragraphs": ["само един"]}, "end_turn"),
    ({"paragraphs": ["1", "2", "3", "4"]}, "refusal"),
])
def test_ai_failure_falls_back_to_templates(payload, stop):
    client, _ = fake_client(payload, stop)
    d = ai_text.draft("obosnovka", POS, EMP, client=client, recruitment_confirmed=True)
    assert d.source == "template" and len(d.fields["obosnovka"].split("\n")) == 4
    assert d.warnings and "AI не успя" in d.warnings[0]


def test_dotenv_loader_does_not_override(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# comment\nANTHROPIC_API_KEY="sk-test"\nexport OTHER_X=1\nAIRTABLE_TOKEN=keep\n', encoding="utf-8")
    monkeypatch.setenv("AIRTABLE_TOKEN", "already")
    monkeypatch.delenv("OTHER_X", raising=False)
    ai_text.load_dotenv(env)
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-test" and os.environ["OTHER_X"] == "1"
    assert os.environ["AIRTABLE_TOKEN"] == "already"
    monkeypatch.delenv("OTHER_X")
    ai_text.load_dotenv(tmp_path / "missing.env")  # no file: nothing happens


def test_route_fills_from_unsaved_form_values(client):
    from tests.test_app import _employer, _id_from
    eid = _id_from(client.post("/employers/new", data=_employer("ФИРМА ООД")))
    page = client.get(f"/employers/{eid}/positions/new").get_data(as_text=True)
    assert 'data-ai="obosnovka"' in page and "AI не е включен" in page
    r = client.post(f"/employers/{eid}/positions/ai-draft", data={"kind": "obosnovka_ext", "title": "Готвач",
                                                                      "ai_recruit": "1"})
    data = r.get_json()
    assert r.status_code == 200 and data["source"] == "template"
    assert "„Готвач“" in data["fields"]["obosnovka_ext"] and len(data["fields"]["obosnovka_ext"].split("\n")) == 5
    assert client.post(f"/employers/{eid}/positions/ai-draft", data={"kind": "x"}).status_code == 400
    assert client.post("/employers/9999/positions/ai-draft", data={"kind": "dh"}).status_code == 404
