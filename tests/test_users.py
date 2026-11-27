"""Stage 4 of the задание: users, super user rights, Assigned and the change history."""
from pathlib import Path

from conftest import make_user
from docautomate.db import connect

from test_app import _employer, _id_from, _setup_case


def _db(app):
    return connect(Path(app.config["DATABASE"]))


def _login(app, username, password="parola-123"):
    c = app.test_client()
    r = c.post("/login", data={"username": username, "password": password})
    return c, r


def test_first_start_asks_for_a_super_user(app):
    c = app.test_client()
    r = c.get("/candidates")
    assert r.status_code == 302 and "/setup" in r.headers["Location"]
    r = c.post("/setup", data={"username": "shef", "full_name": "Шеф", "password": "kratka", "password2": "kratka"})
    assert "поне 8 знака" in r.data.decode()
    r = c.post("/setup", data={"username": "shef", "full_name": "Шеф", "password": "dobra-parola",
                               "password2": "dobra-parola"})
    assert r.status_code == 302
    u = _db(app).execute("SELECT * FROM app_user").fetchone()
    assert u["username"] == "shef" and u["is_super"] == 1 and "dobra-parola" not in u["password_hash"]
    assert c.get("/candidates").status_code == 200
    # setup is closed once a user exists
    assert "/login" in app.test_client().get("/setup").headers["Location"]


def test_every_page_needs_login(client, app):
    anon = app.test_client()
    for url in ("/", "/candidates", "/employers", "/schedule", "/templates", "/cases", "/history", "/users"):
        r = anon.get(url)
        assert r.status_code == 302 and "/login" in r.headers["Location"], url
    r = anon.post("/schedule/1", json={"status": "Нов"})
    assert r.status_code == 401
    c, r = _login(app, "test", "wrong")
    assert r.status_code == 200 and "Грешно име или парола" in r.data.decode()


def test_plain_user_works_but_cannot_delete_or_see_history(client, app):
    eid, pid, cid, case_id = _setup_case(client, app)
    make_user(app, "ivana", "Ивана Колева")
    c, r = _login(app, "ivana")
    assert r.status_code == 302
    assert c.get(f"/candidates/{cid}").status_code == 200
    r = c.post(f"/schedule/{cid}", json={"filed_date": "02.02.2026"})
    assert r.json["ok"]
    html = c.get(f"/candidates/{cid}").data.decode()
    assert "Изтрий работника" not in html and "История на промените" not in html
    for url in ("/history", "/users"):
        assert c.get(url).status_code == 403
    assert c.post(f"/candidates/{cid}/delete").status_code == 403
    assert c.post(f"/employers/{eid}/delete").status_code == 403
    assert _db(app).execute("SELECT count(*) FROM candidate").fetchone()[0] == 1


def test_super_user_deletes_and_history_keeps_it(client, app):
    eid, pid, cid, case_id = _setup_case(client, app)
    client.post(f"/cases/{case_id}/generate")
    r = client.post(f"/employers/{eid}/delete", follow_redirects=True)
    assert "не се изтрива, докато има работници" in r.data.decode()
    r = client.post(f"/candidates/{cid}/delete", follow_redirects=True)
    assert "е изтрит" in r.data.decode()
    c = _db(app)
    assert c.execute("SELECT count(*) FROM candidate").fetchone()[0] == 0
    assert c.execute('SELECT count(*) FROM "case"').fetchone()[0] == 0
    r = client.post(f"/employers/{eid}/delete", follow_redirects=True)
    assert c.execute("SELECT count(*) FROM employer").fetchone()[0] == 0
    html = client.get("/history").data.decode()
    assert "изтриване" in html and "Тестова Анна" in html and "ТЕСТ ЕООД" in html


def test_history_records_who_changed_which_field(client, app):
    eid, pid, cid, case_id = _setup_case(client, app)
    make_user(app, "ivana", "Ивана Колева")
    c, _ = _login(app, "ivana")
    c.post(f"/employers/{eid}", data=_employer("ТЕСТ ЕООД", phone="+359 999"))
    c.post(f"/schedule/{cid}", json={"status": "Готови документи"})
    rows = _db(app).execute("SELECT * FROM audit_log WHERE username='Ивана Колева' ORDER BY id").fetchall()
    fields = {(r["entity"], r["field"]): (r["old_value"], r["new_value"]) for r in rows}
    assert fields[("employer", "phone")] == ("+359000", "+359 999")
    assert fields[("candidate", "status")] == ("Нов", "Готови документи")
    st = _db(app).execute("SELECT changed_by FROM status_history").fetchone()[0]
    assert st == "Ивана Колева"
    # the creation by the test super user is there too
    assert _db(app).execute("SELECT count(*) FROM audit_log WHERE action='create' AND entity='candidate'"
                            " AND username='Тест Тестов'").fetchone()[0] == 1


def test_assigned_only_active_users_and_shown_in_schedule(client, app):
    eid, pid, cid, case_id = _setup_case(client, app)
    make_user(app, "ivana", "Ивана Колева")
    make_user(app, "spren", "Спрян Човек")
    c = _db(app)
    c.execute("UPDATE app_user SET is_active=0 WHERE username='spren'")
    c.commit()
    ivana = c.execute("SELECT id FROM app_user WHERE username='ivana'").fetchone()[0]
    spren = c.execute("SELECT id FROM app_user WHERE username='spren'").fetchone()[0]
    assert client.post(f"/schedule/{cid}", json={"assigned_user_id": str(spren)}).status_code == 422
    r = client.post(f"/schedule/{cid}", json={"assigned_user_id": str(ivana)})
    assert r.json["ok"] and r.json["assigned_user_id"] == ivana
    html = client.get(f"/schedule?assigned={ivana}").data.decode()
    assert "Testova Anna" in html
    assert "Testova Anna" not in client.get("/schedule?assigned=-").data.decode()
    html = client.get("/schedule?group=assigned").data.decode()
    assert 'class="group-head">Ивана Колева' in html
    client.post(f"/schedule/{cid}", json={"assigned_user_id": ""})
    assert c.execute("SELECT assigned_user_id FROM candidate WHERE id=?", (cid,)).fetchone()[0] is None
    assert "Без отговорник" in client.get("/schedule?group=assigned").data.decode()


def test_user_admin_and_own_password(client, app):
    r = client.post("/users", data={"username": "nov", "full_name": "Нов Колега", "password": "parola-123"})
    assert r.status_code == 302
    c = _db(app)
    uid = c.execute("SELECT id FROM app_user WHERE username='nov'").fetchone()[0]
    nov, r = _login(app, "nov")
    assert r.status_code == 302
    r = nov.post("/account", data={"old_password": "parola-123", "password": "nova-parola-1", "password2": "nova-parola-1"})
    assert r.status_code == 302
    assert _login(app, "nov", "nova-parola-1")[1].status_code == 302
    # the super user stops the account: the open session ends too
    client.post(f"/users/{uid}", data={"full_name": "Нов Колега"})
    assert nov.get("/candidates").status_code == 302
    assert _login(app, "nov", "nova-parola-1")[1].status_code == 200
    # nobody can take super rights or access away from themselves
    me = c.execute("SELECT id FROM app_user WHERE username='test'").fetchone()[0]
    r = client.post(f"/users/{me}", data={"full_name": "Тест", "is_active": "1"}, follow_redirects=True)
    assert "на себе си" in r.data.decode()
    assert c.execute("SELECT is_super FROM app_user WHERE id=?", (me,)).fetchone()[0] == 1


def test_login_redirect_only_to_own_pages(app):
    make_user(app, "u1")
    c = app.test_client()
    r = c.post("/login?next=//evil.example.com/x", data={"username": "u1", "password": "parola-123"})
    assert r.headers["Location"] == "/"
    r = app.test_client().post("/login?next=/schedule", data={"username": "u1", "password": "parola-123"})
    assert r.headers["Location"] == "/schedule"
