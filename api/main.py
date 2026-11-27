"""
The ZeeNote API. The web app (web/) calls it to sign in, write a report from notes, save it, and change a team's template
and rules. The writer and the checks are the same code as the Streamlit app (checker/).

Run it with:  uvicorn api.main:app --reload
"""

import json
import re
import secrets
import sqlite3
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator

load_dotenv()  # GROQ_API_KEY from .env, before the checker reads it

from api import db  # noqa: E402
from checker.markup import to_html, to_slack  # noqa: E402
from checker.report import count, run_checks  # noqa: E402
from checker.result import PASS, SKIP  # noqa: E402
from checker.styles import Style, slugify  # noqa: E402
from checker.validation import validate_style  # noqa: E402
from checker.writer import GREETING, UNUSED_RULES, Draft, Layout, Settings, Task, WriterError, extract, render, rules_for_layout, settings_questions, unknown_terms  # noqa: E402
from views.points import points_to_check, split_point  # noqa: E402

REPO = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+")
SESSION_DAYS = 14  # a sign-in lasts this long
MOST_TRIES, LOCK_SECONDS = 10, 15 * 60  # wrong passwords for one email before it waits


def markup(text: str) -> dict:
    """
    The report for the preview, and for pasting into Slack.
    """
    return {"html": to_html(text), "slack": to_slack(text)}


class Login(BaseModel):
    email: str
    password: str


LONGEST_REPORT = 20_000  # characters; a daily report is far shorter
Answer = Annotated[str, Field(max_length=500)]


def near_today(day: date) -> date:
    if abs((day - date.today()).days) > 366:
        raise ValueError("Pick a date within a year of today.")
    return day


def one_line(value: str) -> str:
    return " ".join(value.split())


class WriteIn(BaseModel):
    team_id: int
    notes: str = Field(max_length=10_000)  # the writer itself takes up to 8,000 and says so
    day: date
    first_section: Literal["Yesterday", "Weekend"] = "Yesterday"
    done_hours: float | None = Field(None, ge=0, le=24)
    plan_hours: float | None = Field(None, ge=0, le=24)
    reviewer: str = Field("", max_length=60)
    repo: str = Field("", max_length=200)
    greeting: str = Field("", max_length=300)
    answers: list[Answer] = Field([], max_length=50)  # to the questions about the notes, written as notes
    check_ai: bool = True

    _day = field_validator("day")(near_today)

    # on one line: a line break in them would add parts of its own to the report, such as a heading
    @field_validator("reviewer", "greeting")
    @classmethod
    def on_one_line(cls, value: str) -> str:
        return one_line(value)


class CheckIn(BaseModel):
    team_id: int
    text: str = Field(max_length=LONGEST_REPORT)
    questions: list[Answer] = Field([], max_length=50)
    check_ai: bool = True


class TextIn(BaseModel):
    text: str = Field(max_length=LONGEST_REPORT)


class ReportIn(BaseModel):
    team_id: int
    day: date
    notes: str = Field("", max_length=12_000)  # the notes with the answers
    text: str = Field(max_length=LONGEST_REPORT)

    _day = field_validator("day")(near_today)


class Rule(BaseModel, extra="allow"):
    id: str
    check: str
    title: str = ""
    enabled: bool = True


class LayoutIn(BaseModel):
    """
    The team's format of the report: its section names and a few details. See Layout.
    """

    done: str = "Yesterday"
    weekend: str = "Weekend"
    today: str = "Today"
    blockers: str = "Blockers"
    notes: str = "Notes"
    icons: bool = True
    hours: bool = True
    links: bool = True
    greeting: bool = True

    @field_validator("done", "weekend", "today", "blockers", "notes")
    @classmethod
    def plain_name(cls, name: str) -> str:
        name = " ".join(name.split())
        if not name:
            raise ValueError("Write a name for each section.")
        if len(name) > 30 or re.search(r"[*_`#\[\]/@:<>]", name):
            raise ValueError("Keep section names short, with letters, numbers and spaces only.")
        return name

    @model_validator(mode="after")
    def different_names(self) -> "LayoutIn":
        names = [self.done, self.weekend, self.today, self.blockers, self.notes]
        if len({name.lower() for name in names}) < len(names):
            raise ValueError("Give each section a different name.")
        return self


def plain_text(value: str, problem: str, longest: int = 60) -> str:
    value = " ".join(value.split())
    if not value or len(value) > longest:
        raise ValueError(problem)
    return value


def email_address(value: str, problem: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError(problem)
    return value


class CompanyIn(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def company_name(cls, name: str) -> str:
        return plain_text(name, "Write the company's name, up to 60 characters.")


class NewCompanyIn(CompanyIn):
    owner_name: str
    owner_email: str

    @field_validator("owner_name")
    @classmethod
    def person_name(cls, name: str) -> str:
        return plain_text(name, "Write the owner's name.")

    @field_validator("owner_email")
    @classmethod
    def email(cls, email: str) -> str:
        return email_address(email, "Write the owner's email, such as nora@northwind.ai.")


class TeamIn(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def team_name(cls, name: str) -> str:
        return plain_text(name, "Write the team's name, up to 40 characters.", 40)


class MemberIn(BaseModel):
    name: str
    email: str
    role: Literal["Manager", "Member"] = "Member"

    @field_validator("name")
    @classmethod
    def person_name(cls, name: str) -> str:
        return plain_text(name, "Write their name.")

    @field_validator("email")
    @classmethod
    def email(cls, email: str) -> str:
        return email_address(email, "Write their email, such as olivia@northwind.ai.")


@contextmanager
def unique(message: str):
    """
    A name or email that another request took at the same moment gets the same message as one taken before.
    """
    try:
        yield
    except sqlite3.IntegrityError as e:
        raise HTTPException(422, message) from e


class TemplateIn(BaseModel):
    rules: list[Rule]
    layout: LayoutIn = LayoutIn()


# A short made-up report, to show a team's format before it's saved
SAMPLE_DRAFT = Draft(
    done=[
        Task("Booking list shows the wrong date", issue="95", label="FIX", refs=["PR #102"], ref_statuses={"PR #102": "Merged"}),
        Task("Practiced the project presentation", status="Done"),
    ],
    plans=[Task("Add validation to the password reset form", issue="97", label="CHORE")],
    blockers=["Waiting for QA validation on staging"],
)


def create_app(db_path: Path = db.DB_PATH) -> FastAPI:
    db.setup(db_path)
    app = FastAPI(title="ZeeNote API")
    app.state.db_path = db_path

    def database(request: Request):
        connection = db.connect(request.app.state.db_path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    # "function": the changes are committed before the reply is sent, so a request right after it sees them
    Database = Depends(database, scope="function")

    def signed_in(authorization: str = Header(""), conn: sqlite3.Connection = Database) -> sqlite3.Row:
        token = authorization.removeprefix("Bearer ").strip()
        user = conn.execute(
            "select users.* from sessions join users using (email) where token = ? and sessions.created_at > datetime('now', ?)", (token, f"-{SESSION_DAYS} days")
        ).fetchone()
        if not token or not user:
            raise HTTPException(401, "Please sign in again.")
        return user

    def team_role(conn, user, team_id: int) -> str:
        """
        Owner, Manager or Member for this team, or "" when the person isn't in it. A team of another company doesn't
        exist for them, so nothing shows that it's there.
        """
        if not conn.execute("select 1 from teams where id = ? and company_id = ?", (team_id, user["company_id"])).fetchone():
            raise HTTPException(404, "This team doesn't exist.")
        if user["owner"]:
            return "Owner"
        row = conn.execute("select role from members where team_id = ? and email = ?", (team_id, user["email"])).fetchone()
        return row["role"] if row else ""

    def teams_of(conn, user) -> list[dict]:
        """
        The teams a person sees: all of their company's for the owner, the ones they're in for the others. Only ever
        teams of their own company, so a membership that crosses companies shows nothing.
        """
        if user["owner"]:
            rows = conn.execute("select id, name, 'Owner' as role from teams where company_id = ? order by id", (user["company_id"],))
        else:
            rows = conn.execute(
                "select teams.id, teams.name, members.role from members join teams on teams.id = team_id where email = ? and teams.company_id = ? order by teams.id",
                (user["email"], user["company_id"]),
            )
        return [dict(row) for row in rows]

    def owns_team(conn, user, team_id: int) -> None:
        if team_role(conn, user, team_id) != "Owner":
            raise HTTPException(403, "Only the company's owner can change its teams.")

    def people_of(conn, team_id: int) -> list[dict]:
        rows = conn.execute("select email, name, role from members join users using (email) where team_id = ? order by role, name", (team_id,))
        return [dict(row) for row in rows]

    def in_team(conn, user, team_id: int) -> None:
        if team_role(conn, user, team_id) not in ("Manager", "Member"):
            raise HTTPException(403, "You aren't in this team.")

    def template(conn, team_id: int) -> dict:
        data = json.loads(conn.execute("select data from templates where team_id = ?", (team_id,)).fetchone()["data"])
        # an older template has no format yet, and the settings that each person has now
        return {"rules": data["rules"], "layout": {**asdict(Layout()), **data.get("layout", {})}}

    def style_of(data: dict) -> Style:
        rules = [{key: value for key, value in rule.items() if key != "enabled"} for rule in data["rules"] if rule.get("enabled", True)]
        rules = rules_for_layout(rules, Layout(**data["layout"]))  # the section rules use the team's names
        return Style("daily_report", "Daily report", [rule for rule in rules if rule["id"] not in UNUSED_RULES])

    def checked(text: str, data: dict, questions: list[str], check_ai: bool, edited: bool) -> dict:
        results = run_checks(text, style_of(data), use_llm=check_ai)
        not_checked, points = count(results, SKIP), points_to_check(questions, results, edited=edited)
        return {
            **markup(text),
            "points": points,
            "asks": [split_point(point) for point in points],  # each item of a question, to answer on its own
            "rules": [{"id": result.rule_id, "title": result.title, "status": result.status} for result in results],
            "summary": f"{count(results, PASS)} of {len(results) - not_checked} rules passed" + (f", {not_checked} not checked" if not_checked else ""),
        }

    failures: dict[str, list[float]] = defaultdict(list)  # wrong passwords by email, in this run of the API

    @app.post("/api/login")
    def login(body: Login, conn: sqlite3.Connection = Database):
        email = body.email.strip().lower()
        now = time.monotonic()
        recent = failures[email] = [moment for moment in failures[email] if now - moment < LOCK_SECONDS]
        if len(recent) >= MOST_TRIES:
            raise HTTPException(429, "Too many wrong passwords. Wait 15 minutes and try again.")
        user = conn.execute("select * from users where email = ?", (email,)).fetchone()
        if not user or not secrets.compare_digest(body.password.encode(), db.FAKE_PASSWORD.encode()):
            recent.append(now)
            raise HTTPException(401, "Wrong email or password.")
        failures.pop(email, None)
        conn.execute("delete from sessions where created_at <= datetime('now', ?)", (f"-{SESSION_DAYS} days",))  # old sign-ins
        if user["admin"] and not db.PASSWORD_SET:
            raise HTTPException(401, "The ZeeNote admin signs in only with a password set as ZEENOTE_PASSWORD in .env.")
        token = secrets.token_urlsafe(32)
        conn.execute("insert into sessions (token, email) values (?, ?)", (token, user["email"]))
        return {"token": token}

    @app.post("/api/logout")
    def logout(authorization: str = Header(""), conn: sqlite3.Connection = Database):
        conn.execute("delete from sessions where token = ?", (authorization.removeprefix("Bearer ").strip(),))
        return {"ok": True}

    @app.get("/api/me")
    def me(user=Depends(signed_in), conn: sqlite3.Connection = Database):
        company = conn.execute("select name from companies where id = ?", (user["company_id"],)).fetchone()
        return {
            "email": user["email"], "name": user["name"], "owner": bool(user["owner"]), "admin": bool(user["admin"]),
            "teams": teams_of(conn, user), "company": company["name"] if company else "",
        }

    @app.put("/api/company")
    def rename_company(body: CompanyIn, user=Depends(signed_in), conn: sqlite3.Connection = Database):
        """
        Only the company's owner renames it. ZeeNote's admins see the name, but don't change it.
        """
        if not user["owner"]:
            raise HTTPException(403, "Only the company's owner can change its name.")
        taken = "Another company already has this name."
        if conn.execute("select 1 from companies where name = ? collate nocase and id != ?", (body.name, user["company_id"])).fetchone():
            raise HTTPException(422, taken)
        with unique(taken):
            conn.execute("update companies set name = ? where id = ?", (body.name, user["company_id"]))
        return {"name": body.name}

    @app.post("/api/teams")
    def add_team(body: TeamIn, user=Depends(signed_in), conn: sqlite3.Connection = Database):
        """
        A new team of the owner's company, with the built-in template.
        """
        if not user["owner"]:
            raise HTTPException(403, "Only the company's owner can add teams.")
        taken = "Your company already has a team with this name."
        if conn.execute("select 1 from teams where company_id = ? and name = ? collate nocase", (user["company_id"], body.name)).fetchone():
            raise HTTPException(422, taken)
        with unique(taken):
            team_id = db.add_team(conn, user["company_id"], body.name)
        return {"id": team_id, "name": body.name}

    @app.get("/api/teams/{team_id}/people")
    def team_people(team_id: int, user=Depends(signed_in), conn: sqlite3.Connection = Database):
        owns_team(conn, user, team_id)
        return people_of(conn, team_id)

    @app.put("/api/teams/{team_id}/people")
    def add_person(team_id: int, body: MemberIn, user=Depends(signed_in), conn: sqlite3.Connection = Database):
        """
        Adds someone to the team, or changes their role. Someone new joins the owner's company and signs in with the
        shared password of v1.
        """
        owns_team(conn, user, team_id)
        person = conn.execute("select * from users where email = ?", (body.email,)).fetchone()
        if person and (person["company_id"] != user["company_id"] or person["admin"]):
            raise HTTPException(422, "This email belongs to someone outside your company.")
        if person and person["owner"]:
            raise HTTPException(422, "The owner already sees every team.")
        if not person:
            conn.execute("insert into users (email, name, company_id) values (?, ?, ?)", (body.email, body.name, user["company_id"]))
        conn.execute(
            "insert into members (team_id, email, role) values (?, ?, ?) on conflict (team_id, email) do update set role = excluded.role",
            (team_id, body.email, body.role),
        )
        return people_of(conn, team_id)

    @app.delete("/api/teams/{team_id}/people/{email}")
    def remove_person(team_id: int, email: str, user=Depends(signed_in), conn: sqlite3.Connection = Database):
        """
        Takes someone out of the team. Their reports and their place in the company stay.
        """
        owns_team(conn, user, team_id)
        if not conn.execute("delete from members where team_id = ? and email = ?", (team_id, email.lower())).rowcount:
            raise HTTPException(404, "They aren't in this team.")
        if not conn.execute("select 1 from members where email = ?", (email.lower(),)).fetchone():
            conn.execute("delete from sessions where email = ?", (email.lower(),))  # in no team any more: signed out
        return people_of(conn, team_id)

    @app.get("/api/console")
    def console(user=Depends(signed_in), conn: sqlite3.Connection = Database):
        """
        ZeeNote's own overview, for its admins: numbers only, never a company's reports or notes.
        """
        if not user["admin"]:
            raise HTTPException(403, "Only ZeeNote admins can open the console.")
        rows = conn.execute(
            """
            select companies.id, companies.name,
                (select group_concat(name, ', ') from users where company_id = companies.id and owner = 1) as owner,
                (select count(*) from users where company_id = companies.id) as people,
                (select count(*) from teams where company_id = companies.id) as teams,
                (select count(*) from reports join teams on teams.id = team_id where teams.company_id = companies.id) as reports,
                (select count(*) from reports join teams on teams.id = team_id
                    where teams.company_id = companies.id and date(reports.created_at) = date('now')) as reports_today
            from companies order by companies.id
            """
        )
        return {"companies": [{**dict(row), "owner": row["owner"] or ""} for row in rows]}

    @app.post("/api/companies")
    def add_company(body: NewCompanyIn, user=Depends(signed_in), conn: sqlite3.Connection = Database):
        """
        A new company with its owner, added by a ZeeNote admin. The owner signs in with the shared password of v1.
        """
        if not user["admin"]:
            raise HTTPException(403, "Only ZeeNote admins can add a company.")
        name_taken, email_taken = "A company with this name already uses ZeeNote.", "Someone with this email already uses ZeeNote."
        if conn.execute("select 1 from companies where name = ? collate nocase", (body.name,)).fetchone():
            raise HTTPException(422, name_taken)
        taken_by = conn.execute("select * from users where email = ?", (body.owner_email,)).fetchone()
        if taken_by and (taken_by["owner"] or taken_by["admin"] or conn.execute("select 1 from reports where email = ?", (body.owner_email,)).fetchone()):
            raise HTTPException(422, email_taken)
        if taken_by:  # added to a team by another company's owner, but never used: the address goes to its real owner
            for table in ("members", "settings", "sessions", "users"):
                conn.execute(f"delete from {table} where email = ?", (body.owner_email,))
        with unique(name_taken):
            company_id = conn.execute("insert into companies (name) values (?)", (body.name,)).lastrowid
        with unique(email_taken):
            conn.execute("insert into users (email, name, company_id, owner) values (?, ?, ?, 1)", (body.owner_email, body.owner_name, company_id))
        return {"id": company_id, "name": body.name}

    @app.post("/api/reports/write")
    def write(body: WriteIn, user=Depends(signed_in), conn: sqlite3.Connection = Database):
        in_team(conn, user, body.team_id)
        data = template(conn, body.team_id)
        repo, reviewer = body.repo.strip().rstrip("/"), body.reviewer.strip().lstrip("@")
        if repo and not REPO.fullmatch(repo):
            raise HTTPException(422, "Write a repo link such as https://github.com/acme/app, or leave it empty.")
        mine = {"reviewer": reviewer, "first_section": body.first_section, "done_hours": body.done_hours, "plan_hours": body.plan_hours, "repo": repo, "greeting": body.greeting}
        settings = Settings(body.day, reviewer, body.first_section, body.done_hours, body.plan_hours, repo, body.greeting)
        notes = "\n".join([body.notes.rstrip(), *[answer.strip() for answer in body.answers if answer.strip()]])
        try:
            draft = extract(notes, day=body.day, first_section=body.first_section)
        except WriterError as e:
            raise HTTPException(422, str(e)) from e
        text = render(draft, settings, Layout(**data["layout"]))
        questions = settings_questions(draft, settings) + draft.questions
        known = [term for rule in data["rules"] if rule.get("enabled", True) for term in rule.get("known_terms") or []]
        if terms := unknown_terms(draft, known):
            questions.append("A reader who isn't technical may not know: " + ", ".join(terms))
        result = {"notes": notes, "day": body.day.isoformat(), "text": text, "questions": questions, **checked(text, data, questions, body.check_ai, edited=False)}
        # last, after the AI's work: writing locks the database until the reply
        conn.execute("insert or replace into settings (email, team_id, data) values (?, ?, ?)", (user["email"], body.team_id, json.dumps(mine)))
        return result

    @app.post("/api/reports/check")
    def check(body: CheckIn, user=Depends(signed_in), conn: sqlite3.Connection = Database):
        """
        Checks an edited report again. The questions of the first check stay, unless the edits answered them.
        """
        in_team(conn, user, body.team_id)
        return checked(body.text, template(conn, body.team_id), body.questions, body.check_ai, edited=True)

    @app.post("/api/template/preview")
    def preview(body: LayoutIn, user=Depends(signed_in)):
        """
        A made-up report in a format that isn't saved yet.
        """
        settings = Settings(date.today(), "Illia", "Yesterday", 8.0, 8.0, "https://github.com/acme/app", GREETING)
        return markup(render(SAMPLE_DRAFT, settings, Layout(**body.model_dump())))

    @app.post("/api/render")
    def rendered(body: TextIn, user=Depends(signed_in)):
        return markup(body.text)

    @app.post("/api/reports")
    def save(body: ReportIn, user=Depends(signed_in), conn: sqlite3.Connection = Database):
        in_team(conn, user, body.team_id)
        if not body.text.strip():
            raise HTTPException(422, "The report is empty.")
        key = (user["email"], body.team_id, body.day.isoformat())
        replaced = conn.execute("select 1 from reports where email = ? and team_id = ? and day = ?", key).fetchone() is not None
        conn.execute(
            "insert into reports (email, team_id, day, notes, text) values (?, ?, ?, ?, ?)"
            " on conflict (email, team_id, day) do update set notes = excluded.notes, text = excluded.text, created_at = datetime('now')",
            (*key, body.notes, body.text),
        )
        report_id = conn.execute("select id from reports where email = ? and team_id = ? and day = ?", key).fetchone()["id"]
        return {"id": report_id, "replaced": replaced}

    @app.get("/api/reports")
    def my_reports(user=Depends(signed_in), conn: sqlite3.Connection = Database):
        rows = conn.execute(
            "select reports.id, day, team_id, teams.name as team, substr(text, 1, 300) as text, created_at"
            " from reports join teams on teams.id = team_id where email = ? order by day desc, reports.id desc",
            (user["email"],),
        )
        return [dict(row) for row in rows]

    @app.get("/api/reports/{report_id}")
    def one_report(report_id: int, user=Depends(signed_in), conn: sqlite3.Connection = Database):
        row = conn.execute(
            "select reports.*, teams.name as team from reports join teams on teams.id = team_id where reports.id = ? and email = ?", (report_id, user["email"])
        ).fetchone()
        if not row:
            raise HTTPException(404, "This report doesn't exist.")
        return {**dict(row), **markup(row["text"])}

    @app.delete("/api/reports/{report_id}")
    def delete_report(report_id: int, user=Depends(signed_in), conn: sqlite3.Connection = Database):
        if not conn.execute("delete from reports where id = ? and email = ?", (report_id, user["email"])).rowcount:
            raise HTTPException(404, "This report doesn't exist.")
        return {"ok": True}

    @app.get("/api/teams/{team_id}/settings")
    def my_settings(team_id: int, user=Depends(signed_in), conn: sqlite3.Connection = Database):
        """
        What this person used for the team's last report. The first time, the reviewer is the team's manager.
        """
        in_team(conn, user, team_id)
        row = conn.execute("select data from settings where email = ? and team_id = ?", (user["email"], team_id)).fetchone()
        if row:  # every field is needed now, so one left empty before gets its default
            saved = json.loads(row["data"])
            return {**saved, **{key: value for key, value in db.default_settings().items() if key in ("repo", "greeting") and not saved.get(key)}}
        manager = conn.execute(
            "select name from members join users using (email) where team_id = ? and role = 'Manager' and email != ? order by name", (team_id, user["email"])
        ).fetchone()
        return db.default_settings(manager["name"] if manager else "")

    @app.get("/api/teams/{team_id}/template")
    def get_template(team_id: int, user=Depends(signed_in), conn: sqlite3.Connection = Database):
        role = team_role(conn, user, team_id)
        if not role:
            raise HTTPException(403, "You aren't in this team.")
        row = conn.execute("select updated_at, updated_by from templates where team_id = ?", (team_id,)).fetchone()
        return {**template(conn, team_id), "can_edit": role in ("Owner", "Manager"), "updated_at": row["updated_at"], "updated_by": row["updated_by"]}

    def save_template(conn, user, team_id: int, data: dict) -> dict:
        if team_role(conn, user, team_id) not in ("Owner", "Manager"):
            raise HTTPException(403, "Only the team's managers and the owner can change the template.")
        conn.execute("update templates set data = ?, updated_at = datetime('now'), updated_by = ? where team_id = ?", (json.dumps(data), user["name"], team_id))
        return get_template(team_id, user, conn)

    @app.put("/api/teams/{team_id}/template")
    def put_template(team_id: int, body: TemplateIn, user=Depends(signed_in), conn: sqlite3.Connection = Database):
        data = body.model_dump()
        ids = {rule["id"] for rule in data["rules"]}
        for rule in data["rules"]:
            if not rule["id"]:  # a new rule of the team gets its ID from the title, short enough and not used yet
                base = "custom_" + (slugify(rule["title"])[:36].strip("-_") or "rule")
                rule["id"] = next(f"{base}_{n}" if n else base for n in range(len(ids) + 1) if (f"{base}_{n}" if n else base) not in ids)
                ids.add(rule["id"])
        problems = validate_style(Style("daily_report", "Daily report", data["rules"]))
        if problems:
            raise HTTPException(422, " ".join(problems))
        return save_template(conn, user, team_id, data)

    @app.post("/api/teams/{team_id}/template/reset")
    def reset_template(team_id: int, user=Depends(signed_in), conn: sqlite3.Connection = Database):
        return save_template(conn, user, team_id, db.default_template())

    return app


app = create_app()
