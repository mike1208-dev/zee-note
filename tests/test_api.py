import os
import sqlite3
import tempfile
from datetime import date

import pytest

# Loading the API sets up its database, so the tests point it at a throwaway one first, never at data/zeenote.db
os.environ["ZEENOTE_DB"] = os.path.join(tempfile.mkdtemp(), "import.db")

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api import db, main  # noqa: E402
from checker.writer import Draft, Task  # noqa: E402

DAY = date.today().isoformat()  # a report must be within a year of today


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "PASSWORD_SET", True)  # as with a password in .env
    return TestClient(main.create_app(tmp_path / "test.db"))


def sign_in(client, who: str) -> dict:
    email = dict(db.USERS)[who.capitalize()][0] if who.capitalize() in db.USERS else f"{who}@zeenote.ai"
    token = client.post("/api/login", json={"email": email, "password": db.FAKE_PASSWORD}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def team_id(client, headers, name: str) -> int:
    return next(team["id"] for team in client.get("/api/me", headers=headers).json()["teams"] if team["name"] == name)


@pytest.fixture
def no_ai(monkeypatch):
    """
    The AI's sorting of the notes, without calling Groq.
    """

    def extract(notes, day: date, first_section: str):
        return Draft(done=[Task("Fixed the login page", status="Merged")], plans=[Task("Write the tests")], no_blockers=True, notes=notes)

    monkeypatch.setattr(main, "extract", extract)


def test_wrong_password_and_no_token(client):
    assert client.post("/api/login", json={"email": "mike@zeenote.ai", "password": "wrong"}).status_code == 401
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer made-up"}).status_code == 401


def test_teams_of_each_role(client):
    owner = client.get("/api/me", headers=sign_in(client, "dan")).json()
    assert owner["owner"] and [team["role"] for team in owner["teams"]] == ["Owner"] * 4
    illia = client.get("/api/me", headers=sign_in(client, "illia")).json()
    assert [(team["name"], team["role"]) for team in illia["teams"]] == [("Cova Team", "Manager"), ("Commity Team", "Manager"), ("AI-Training Team", "Manager")]
    token = client.post("/api/login", json={"email": " Mike@ZeeNote.ai", "password": db.FAKE_PASSWORD}).json()["token"]  # not case sensitive
    mike = client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert [(team["name"], team["role"]) for team in mike["teams"]] == [("Cova Team", "Member"), ("AI-Training Team", "Member")]


def test_admin_sees_numbers_only(client, no_ai):
    admin = sign_in(client, "admin")
    me = client.get("/api/me", headers=admin).json()
    assert me["admin"] and not me["owner"] and me["teams"] == []
    mike = sign_in(client, "mike")
    app_team = team_id(client, mike, "Cova Team")
    client.post("/api/reports", headers=mike, json={"team_id": app_team, "day": DAY, "text": "- **Today**"})
    company = client.get("/api/console", headers=admin).json()["companies"][0]
    assert (company["name"], company["owner"], company["people"], company["teams"], company["reports"]) == ("ZeeSpires", "Dan", 7, 4, 1)
    assert client.get(f"/api/teams/{app_team}/template", headers=admin).status_code == 404  # in no company, so no team of one
    assert client.get("/api/console", headers=sign_in(client, "dan")).status_code == 403


def test_old_sample_starts_again(tmp_path):
    path = tmp_path / "old.db"
    with db.connect(path) as old:
        old.execute("create table users (email text primary key, name text not null, owner integer not null default 0)")
        old.execute("insert into users values ('dan@acme.example', 'Ava', 1)")
    db.setup(path)
    with db.connect(path) as new:
        assert new.execute("select email from users where owner = 1").fetchone()[0] == "dan@zeenote.ai"


def test_copies_saved_twice_before_keep_the_newest(tmp_path):
    path = tmp_path / "copies.db"
    db.setup(path)
    with db.connect(path) as old:
        old.execute("drop index one_report_a_day")  # as before the rule
        old.executemany("insert into reports (email, team_id, day, notes, text) values ('mike@zeenote.ai', 1, ?, '', ?)",
                        [(DAY, "first"), (DAY, "newest"), ("2026-11-26", "other day")])
    db.setup(path)
    with db.connect(path) as new:
        assert [row[0] for row in new.execute("select text from reports order by day")] == ["other day", "newest"]


def test_logout(client):
    headers = sign_in(client, "mike")
    client.post("/api/logout", headers=headers)
    assert client.get("/api/me", headers=headers).status_code == 401


def test_first_settings(client):
    mike, illia = sign_in(client, "mike"), sign_in(client, "illia")
    web = team_id(client, mike, "AI-Training Team")
    assert client.get(f"/api/teams/{web}/settings", headers=mike).json() == db.default_settings("Illia")
    assert client.get(f"/api/teams/{web}/settings", headers=illia).json()["reviewer"] == ""  # not himself
    assert client.get(f"/api/teams/{web}/settings", headers=sign_in(client, "leo")).status_code == 403


def test_write_uses_and_keeps_my_settings(client, no_ai):
    mike = sign_in(client, "mike")
    web, app_team = team_id(client, mike, "AI-Training Team"), team_id(client, mike, "Cova Team")
    body = {"team_id": web, "notes": "fixed the login page, merged", "day": DAY, "done_hours": 7, "plan_hours": 8, "reviewer": "@Mina ",
            "repo": "https://github.com/acme/web/", "greeting": "Hello team.", "check_ai": False}
    result = client.post("/api/reports/write", headers=mike, json=body).json()
    assert result["text"].startswith("@Mina  \nHello team.")
    assert "Fixed the login page ― **Merged**" in result["text"] and "(7 hours)" in result["text"]
    assert "<strong>" in result["html"] and '"ops"' in result["slack"]
    assert "rules passed" in result["summary"]
    kept = client.get(f"/api/teams/{web}/settings", headers=mike).json()
    assert (kept["reviewer"], kept["repo"], kept["greeting"], kept["done_hours"]) == ("Mina", "https://github.com/acme/web", "Hello team.", 7)
    assert client.get(f"/api/teams/{app_team}/settings", headers=mike).json()["reviewer"] == "Illia"  # each team has its own
    client.post("/api/reports/write", headers=mike, json={**body, "repo": "", "greeting": ""})
    kept = client.get(f"/api/teams/{web}/settings", headers=mike).json()
    assert (kept["repo"], kept["greeting"]) == (db.DEFAULT_REPO, db.GREETING)  # an empty one gets its default back

    wrong = client.post("/api/reports/write", headers=mike, json={**body, "repo": "github.com/acme"})
    assert wrong.status_code == 422 and "repo link" in wrong.json()["detail"]


def test_answers_join_the_notes(client, no_ai):
    mike = sign_in(client, "mike")
    body = {"team_id": team_id(client, mike, "Cova Team"), "notes": "fixed the login page \n", "day": DAY, "check_ai": False,
            "answers": ["pr 30 is merged", " ", " QA means testing "]}
    result = client.post("/api/reports/write", headers=mike, json=body).json()
    assert result["notes"] == "fixed the login page\npr 30 is merged\nQA means testing"


def test_writer_errors_are_messages(client, monkeypatch):
    mike = sign_in(client, "mike")
    body = {"team_id": team_id(client, mike, "Cova Team"), "notes": " ", "day": DAY, "check_ai": False}
    response = client.post("/api/reports/write", headers=mike, json=body)
    assert response.status_code == 422 and response.json()["detail"] == "Please write some notes first."


def test_only_team_people_write_and_the_owner_doesnt(client, no_ai):
    leo = sign_in(client, "leo")
    app_team = team_id(client, sign_in(client, "mike"), "Cova Team")
    body = {"team_id": app_team, "notes": "fixed it", "day": DAY, "check_ai": False}
    assert client.post("/api/reports/write", headers=leo, json=body).status_code == 403
    assert client.post("/api/reports/write", headers=sign_in(client, "dan"), json=body).status_code == 403
    assert client.post("/api/reports", headers=leo, json={"team_id": app_team, "day": DAY, "text": "x"}).status_code == 403


def test_saved_reports_are_only_mine(client):
    mike, lina = sign_in(client, "mike"), sign_in(client, "lina")
    app_team = team_id(client, mike, "Cova Team")
    report_id = client.post("/api/reports", headers=mike, json={"team_id": app_team, "day": DAY, "notes": "n", "text": "- **Today**"}).json()["id"]
    assert [row["id"] for row in client.get("/api/reports", headers=mike).json()] == [report_id]
    assert client.get("/api/reports", headers=lina).json() == []
    assert client.get(f"/api/reports/{report_id}", headers=lina).status_code == 404
    report = client.get(f"/api/reports/{report_id}", headers=mike).json()
    assert report["team"] == "Cova Team" and "<strong>Today</strong>" in report["html"]
    assert client.post("/api/reports", headers=mike, json={"team_id": app_team, "day": DAY, "text": "  "}).status_code == 422
    again = client.post("/api/reports", headers=mike, json={"team_id": app_team, "day": DAY, "notes": "n2", "text": "- **Today** fixed"}).json()
    assert again == {"id": report_id, "replaced": True}  # the same day's report is replaced, not added
    assert len(client.get("/api/reports", headers=mike).json()) == 1 and "fixed" in client.get(f"/api/reports/{report_id}", headers=mike).json()["text"]
    assert client.delete(f"/api/reports/{report_id}", headers=lina).status_code == 404  # only my own
    assert client.delete(f"/api/reports/{report_id}", headers=mike).status_code == 200
    assert client.get("/api/reports", headers=mike).json() == []


def test_who_can_change_the_template(client):
    illia, mike, yuki, dan = (sign_in(client, who) for who in ("illia", "mike", "yuki", "dan"))
    app_team, support = team_id(client, dan, "Cova Team"), team_id(client, dan, "AI-Training Team")
    data = client.get(f"/api/teams/{app_team}/template", headers=mike).json()
    assert data["can_edit"] is False and len(data["rules"]) == 8
    assert client.put(f"/api/teams/{app_team}/template", headers=mike, json=data).status_code == 403
    assert client.put(f"/api/teams/{app_team}/template", headers=yuki, json=data).status_code == 403
    assert client.get(f"/api/teams/{support}/template", headers=sign_in(client, "lina")).status_code == 403  # not in the team
    rules = [{**rule, "title": "Has the parts"} if rule["id"] == "has_sections" else rule for rule in data["rules"]]
    saved = client.put(f"/api/teams/{app_team}/template", headers=dan, json={**data, "rules": rules}).json()
    assert saved["rules"][0]["title"] == "Has the parts" and saved["updated_by"] == "Dan" and saved["can_edit"]
    assert client.get("/api/teams/999/template", headers=dan).status_code == 404


def test_rules_turned_off_new_and_wrong(client):
    illia = sign_in(client, "illia")
    app_team = team_id(client, illia, "Cova Team")
    data = client.get(f"/api/teams/{app_team}/template", headers=illia).json()
    rules = [{**rule, "enabled": rule["id"] == "has_sections"} for rule in data["rules"]]
    rules.append({"id": "", "check": "llm", "title": "Names the client", "question": "Does it name the client?", "enabled": True})
    saved = client.put(f"/api/teams/{app_team}/template", headers=illia, json={**data, "rules": rules}).json()
    assert saved["rules"][-1]["id"] == "custom_names_the_client"
    result = client.post("/api/reports/check", headers=illia, json={"team_id": app_team, "text": "- **Today**", "check_ai": False}).json()
    assert [rule["title"] for rule in result["rules"]] == ["Has Yesterday / Today / Blockers sections", "Names the client"]
    assert any(point.startswith("Has Yesterday") for point in result["points"])

    no_question = [*data["rules"], {"id": "", "check": "llm", "title": "Empty", "enabled": True}]
    assert client.put(f"/api/teams/{app_team}/template", headers=illia, json={**data, "rules": no_question}).status_code == 422


def test_reset(client):
    illia = sign_in(client, "illia")
    app_team = team_id(client, illia, "Cova Team")
    data = client.get(f"/api/teams/{app_team}/template", headers=illia).json()
    client.put(f"/api/teams/{app_team}/template", headers=illia, json={"rules": data["rules"][:1]})
    reset = client.post(f"/api/teams/{app_team}/template/reset", headers=illia).json()
    assert reset["rules"] == db.default_template()["rules"]


def test_a_team_format_is_used_checked_and_reset(client, no_ai):
    illia, mike = sign_in(client, "illia"), sign_in(client, "mike")
    cova = team_id(client, illia, "Cova Team")
    data = client.get(f"/api/teams/{cova}/template", headers=illia).json()
    assert data["layout"]["done"] == "Yesterday" and data["layout"]["icons"] is True
    layout = {**data["layout"], "done": "Done", "today": "Plan", "icons": False}
    assert client.put(f"/api/teams/{cova}/template", headers=illia, json={**data, "layout": layout}).json()["layout"]["done"] == "Done"
    body = {"team_id": cova, "notes": "fixed the login page, merged", "day": DAY, "done_hours": 7, "plan_hours": 8, "reviewer": "Illia",
            "repo": "", "greeting": "Hi", "check_ai": False}
    result = client.post("/api/reports/write", headers=mike, json=body).json()
    assert "**Done** (7 hours)" in result["text"] and ":dart:" not in result["text"]
    assert {rule["id"]: rule["status"] for rule in result["rules"]}["has_sections"] == "PASS"  # the rule follows the names

    for wrong in ({"done": " "}, {"done": "plan"}, {"today": "**Plan**"}):  # empty, the same as another, markup
        response = client.put(f"/api/teams/{cova}/template", headers=illia, json={**data, "layout": {**layout, **wrong}})
        assert response.status_code == 422
    preview = client.post("/api/template/preview", headers=mike, json={"done": "Shipped"}).json()
    assert "Shipped" in preview["html"]
    assert client.post(f"/api/teams/{cova}/template/reset", headers=illia).json()["layout"]["done"] == "Yesterday"


def test_only_the_owner_renames_the_company(client):
    dan, illia, admin = sign_in(client, "dan"), sign_in(client, "illia"), sign_in(client, "admin")
    assert client.get("/api/me", headers=illia).json()["company"] == "ZeeSpires"
    for someone in (illia, admin):
        assert client.put("/api/company", headers=someone, json={"name": "Other"}).status_code == 403
    assert client.put("/api/company", headers=dan, json={"name": "  "}).status_code == 422
    assert client.put("/api/company", headers=dan, json={"name": " ZeeSpires   Labs "}).json() == {"name": "ZeeSpires Labs"}
    assert client.get("/api/me", headers=illia).json()["company"] == "ZeeSpires Labs"
    assert client.get("/api/console", headers=admin).json()["companies"][0]["name"] == "ZeeSpires Labs"


def test_companies_see_nothing_of_each_other(client, no_ai):
    nora, paul, mike = sign_in(client, "nora"), sign_in(client, "paul"), sign_in(client, "mike")
    me = client.get("/api/me", headers=nora).json()
    assert me["company"] == "Northwind" and [team["name"] for team in me["teams"]] == ["Sales Team"]
    sales, cova = team_id(client, nora, "Sales Team"), team_id(client, mike, "Cova Team")
    for headers, other in ((nora, cova), (paul, cova), (mike, sales)):  # another company's team doesn't exist for them
        assert client.get(f"/api/teams/{other}/template", headers=headers).status_code == 404
        assert client.get(f"/api/teams/{other}/settings", headers=headers).status_code == 404
        assert client.post("/api/reports", headers=headers, json={"team_id": other, "day": DAY, "text": "x"}).status_code == 404
    report = client.post("/api/reports", headers=mike, json={"team_id": cova, "day": DAY, "text": "- **Today**"}).json()["id"]
    assert client.get(f"/api/reports/{report}", headers=paul).status_code == 404
    assert client.put("/api/company", headers=nora, json={"name": "ZeeSpires"}).status_code == 422  # taken
    client.put("/api/company", headers=nora, json={"name": "Northwind Labs"})
    assert client.get("/api/me", headers=mike).json()["company"] == "ZeeSpires"  # only her own company is renamed


def test_the_admin_adds_a_company(client):
    admin = sign_in(client, "admin")
    new = {"name": "Contoso", "owner_name": "Carla", "owner_email": " Carla@Contoso.ai "}
    assert client.post("/api/companies", headers=sign_in(client, "dan"), json=new).status_code == 403
    assert client.post("/api/companies", headers=admin, json=new).json()["name"] == "Contoso"
    assert client.post("/api/companies", headers=admin, json=new).status_code == 422  # the same name
    assert client.post("/api/companies", headers=admin, json={**new, "name": "Other", "owner_email": "dan@zeenote.ai"}).status_code == 422
    assert client.post("/api/companies", headers=admin, json={**new, "name": "Other", "owner_email": "carla"}).status_code == 422
    carla = client.post("/api/login", json={"email": "carla@contoso.ai", "password": db.FAKE_PASSWORD}).json()["token"]
    me = client.get("/api/me", headers={"Authorization": f"Bearer {carla}"}).json()
    assert me["owner"] and me["company"] == "Contoso" and me["teams"] == []
    companies = client.get("/api/console", headers=admin).json()["companies"]
    assert [(row["name"], row["owner"], row["people"], row["teams"]) for row in companies] == [
        ("ZeeSpires", "Dan", 7, 4), ("Northwind", "Nora", 3, 1), ("Contoso", "Carla", 1, 0)]


def test_the_owner_sets_up_teams_and_people(client):
    admin = sign_in(client, "admin")
    client.post("/api/companies", headers=admin, json={"name": "Contoso", "owner_name": "Carla", "owner_email": "carla@contoso.ai"})
    carla = {"Authorization": "Bearer " + client.post("/api/login", json={"email": "carla@contoso.ai", "password": db.FAKE_PASSWORD}).json()["token"]}
    team = client.post("/api/teams", headers=carla, json={"name": " Web  Team "}).json()
    assert team["name"] == "Web Team" and client.post("/api/teams", headers=carla, json={"name": "web team"}).status_code == 422  # the same name
    assert client.post("/api/teams", headers=sign_in(client, "illia"), json={"name": "Mine"}).status_code == 403  # owners only
    people = client.put(f"/api/teams/{team['id']}/people", headers=carla, json={"name": "Raj", "email": "Raj@Contoso.ai", "role": "Manager"}).json()
    assert people == [{"email": "raj@contoso.ai", "name": "Raj", "role": "Manager"}]
    for email in ("mike@zeenote.ai", "admin@zeenote.ai", "carla@contoso.ai"):  # another company's, ZeeNote's own, the owner
        assert client.put(f"/api/teams/{team['id']}/people", headers=carla, json={"name": "X", "email": email}).status_code == 422
    raj = {"Authorization": "Bearer " + client.post("/api/login", json={"email": "raj@contoso.ai", "password": db.FAKE_PASSWORD}).json()["token"]}
    assert client.get("/api/me", headers=raj).json()["teams"] == [{"id": team["id"], "name": "Web Team", "role": "Manager"}]
    cova = team_id(client, sign_in(client, "dan"), "Cova Team")
    assert client.get(f"/api/teams/{cova}/people", headers=carla).status_code == 404  # another company's team
    assert client.delete(f"/api/teams/{team['id']}/people/raj@contoso.ai", headers=carla).json() == []
    assert client.get("/api/me", headers=raj).status_code == 401  # in no team any more: signed out


def test_names_differ_by_more_than_capitals(client):
    admin = sign_in(client, "admin")
    assert client.post("/api/companies", headers=admin, json={"name": "ZEESPIRES", "owner_name": "Z", "owner_email": "z@z.ai"}).status_code == 422
    assert client.put("/api/company", headers=sign_in(client, "nora"), json={"name": "zeespires"}).status_code == 422
    with db.connect(client.app.state.db_path) as conn, pytest.raises(sqlite3.IntegrityError):  # even past the checks
        conn.execute("insert into companies (name) values ('zeeSPIRES')")


def test_a_membership_across_companies_shows_nothing(client):
    paul = sign_in(client, "paul")
    cova = team_id(client, sign_in(client, "mike"), "Cova Team")
    with db.connect(client.app.state.db_path) as conn:
        conn.execute("insert into members values (?, 'paul@northwind.ai', 'Member')", (cova,))
    assert "Cova Team" not in [team["name"] for team in client.get("/api/me", headers=paul).json()["teams"]]


def test_real_companies_stay_when_the_api_starts_again(tmp_path):
    path = tmp_path / "kept.db"
    db.setup(path)
    with db.connect(path) as conn:
        conn.execute("insert into companies (name) values ('Contoso')")
    db.setup(path)
    with db.connect(path) as conn:
        assert conn.execute("select count(*) from companies where name = 'Contoso'").fetchone()[0] == 1


def test_a_name_taken_at_the_same_moment_is_the_same_message():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught, main.unique("Another company already has this name."):
        raise sqlite3.IntegrityError("UNIQUE constraint failed: companies.name")
    assert (caught.value.status_code, caught.value.detail) == (422, "Another company already has this name.")


def test_the_admin_needs_a_password_of_their_own(client, monkeypatch):
    monkeypatch.setattr(db, "PASSWORD_SET", False)  # only the default password
    response = client.post("/api/login", json={"email": "admin@zeenote.ai", "password": db.FAKE_PASSWORD})
    assert response.status_code == 401 and "ZEENOTE_PASSWORD" in response.json()["detail"]
    assert client.post("/api/login", json={"email": "mike@zeenote.ai", "password": db.FAKE_PASSWORD}).status_code == 200


def test_new_rules_get_short_different_ids(client):
    illia = sign_in(client, "illia")
    cova = team_id(client, illia, "Cova Team")
    data = client.get(f"/api/teams/{cova}/template", headers=illia).json()
    new = {"id": "", "check": "llm", "title": "Names the client for every client-facing task done this week", "question": "Does it?", "enabled": True}
    saved = client.put(f"/api/teams/{cova}/template", headers=illia, json={**data, "rules": [*data["rules"], new, new]}).json()
    ids = [rule["id"] for rule in saved["rules"][-2:]]
    assert ids[0] != ids[1] and all(len(rule_id) <= 50 and rule_id.startswith("custom_") for rule_id in ids)


def test_the_report_says_its_day_and_settings_are_kept(client, no_ai):
    mike = sign_in(client, "mike")
    cova = team_id(client, mike, "Cova Team")
    body = {"team_id": cova, "notes": "fixed the login page", "day": DAY, "reviewer": "Illia", "greeting": "Hi", "check_ai": False}
    assert client.post("/api/reports/write", headers=mike, json=body).json()["day"] == DAY
    assert client.get(f"/api/teams/{cova}/settings", headers=mike).json()["greeting"] == "Hi"


def test_many_wrong_passwords_wait(client):
    for _ in range(main.MOST_TRIES):
        assert client.post("/api/login", json={"email": "mike@zeenote.ai", "password": "guess"}).status_code == 401
    assert client.post("/api/login", json={"email": "mike@zeenote.ai", "password": db.FAKE_PASSWORD}).status_code == 429
    assert client.post("/api/login", json={"email": "dan@zeenote.ai", "password": db.FAKE_PASSWORD}).status_code == 200  # others aren't held


def test_a_sign_in_lasts_two_weeks(client):
    mike = sign_in(client, "mike")
    with db.connect(client.app.state.db_path) as conn:
        conn.execute("update sessions set created_at = datetime('now', '-15 days')")
    assert client.get("/api/me", headers=mike).status_code == 401


def test_a_rule_that_could_freeze_the_app_isnt_saved(client):
    illia = sign_in(client, "illia")
    cova = team_id(client, illia, "Cova Team")
    data = client.get(f"/api/teams/{cova}/template", headers=illia).json()
    bad = [{"id": "", "check": "pattern", "title": "Words", "pattern": r"^(\w+\s?)+$", "enabled": True},
           {"id": "", "check": "pattern", "title": "Odd", "pattern": "x", "must": "never", "enabled": True}]
    for rule in bad:
        assert client.put(f"/api/teams/{cova}/template", headers=illia, json={**data, "rules": [*data["rules"], rule]}).status_code == 422
    many = [{"id": "", "check": "llm", "title": f"Rule {n}", "question": "Is it fine?", "enabled": True} for n in range(10)]
    assert client.put(f"/api/teams/{cova}/template", headers=illia, json={**data, "rules": [*data["rules"], *many]}).status_code == 422


def test_sizes_and_dates_have_limits(client, no_ai):
    mike = sign_in(client, "mike")
    cova = team_id(client, mike, "Cova Team")
    body = {"team_id": cova, "notes": "fixed the login page", "day": DAY, "check_ai": False}
    assert client.post("/api/reports/write", headers=mike, json={**body, "notes": "x" * 10_001}).status_code == 422
    assert client.post("/api/reports/write", headers=mike, json={**body, "day": "9999-12-31"}).status_code == 422
    assert client.post("/api/reports", headers=mike, json={"team_id": cova, "day": DAY, "text": "x" * 20_001}).status_code == 422
    # a line break in the reviewer or greeting can't add a heading of its own
    text = client.post("/api/reports/write", headers=mike, json={**body, "reviewer": "Sam\n\n- **Yesterday** (8 hours)", "greeting": "Hi\nthere"}).json()["text"]
    assert text.startswith("@Sam - **Yesterday** (8 hours)  \nHi there")


def test_an_email_never_used_goes_to_its_real_owner(client):
    dan, admin = sign_in(client, "dan"), sign_in(client, "admin")
    cova = team_id(client, dan, "Cova Team")
    client.put(f"/api/teams/{cova}/people", headers=dan, json={"name": "Ceo", "email": "ceo@bigcorp.ai"})
    new = {"name": "BigCorp", "owner_name": "Ceo", "owner_email": "ceo@bigcorp.ai"}
    assert client.post("/api/companies", headers=admin, json=new).status_code == 200
    me = client.post("/api/login", json={"email": "ceo@bigcorp.ai", "password": db.FAKE_PASSWORD}).json()["token"]
    assert client.get("/api/me", headers={"Authorization": f"Bearer {me}"}).json()["company"] == "BigCorp"
    assert "ceo@bigcorp.ai" not in [person["email"] for person in client.get(f"/api/teams/{cova}/people", headers=dan).json()]


def test_a_restored_database_is_kept(tmp_path):
    path = tmp_path / "restored.db"
    db.setup(path)
    with db.connect(path) as conn:
        conn.execute("insert into companies (name) values ('Contoso')")
        conn.execute("pragma user_version = 0")  # as a dump restored with .dump loses it
    db.setup(path)
    with db.connect(path) as conn:
        assert conn.execute("select count(*) from companies where name = 'Contoso'").fetchone()[0] == 1
