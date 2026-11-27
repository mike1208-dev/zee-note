"""
The ZeeNote database: people, teams, each team's template and rules, each person's report settings, saved reports and sign-ins. SQLite for the first
version, so nothing needs to be set up. The sample company is added the first time.
"""

import json
import os
import sqlite3
from dataclasses import asdict
from pathlib import Path

from checker.store import YamlStore
from checker.writer import GREETING, Layout

DB_PATH = Path(os.getenv("ZEENOTE_DB", Path(__file__).resolve().parent.parent / "data" / "zeenote.db"))
# The first version has no real sign-in: every sample account uses this password. Set your own in .env before sharing the app
FAKE_PASSWORD = os.getenv("ZEENOTE_PASSWORD") or "zeenote"
PASSWORD_SET = bool(os.getenv("ZEENOTE_PASSWORD"))  # the ZeeNote admin signs in only then

SCHEMA = """
-- every company that uses ZeeNote. Its people and teams see nothing of the other companies
create table if not exists companies (id integer primary key, name text not null unique);
-- owner: the company's owner. admin: ZeeNote's own staff, in no company, who see numbers but never a company's reports
create table if not exists users (
    email text primary key, name text not null, company_id integer references companies(id),
    owner integer not null default 0, admin integer not null default 0
);
create table if not exists teams (id integer primary key, company_id integer not null references companies(id), name text not null, unique (company_id, name));
create table if not exists members (
    team_id integer not null references teams(id), email text not null references users(email),
    role text not null check (role in ('Manager', 'Member')), primary key (team_id, email)
);
create table if not exists templates (team_id integer primary key references teams(id), data text not null, updated_at text, updated_by text);
-- what each person last used for a team's reports: reviewer, hours, repo link, greeting
create table if not exists settings (email text not null references users(email), team_id integer not null references teams(id), data text not null, primary key (email, team_id));
create table if not exists reports (
    id integer primary key, email text not null references users(email), team_id integer not null references teams(id),
    day text not null, notes text not null, text text not null, created_at text not null default (datetime('now'))
);
create table if not exists sessions (token text primary key, email text not null references users(email), created_at text not null default (datetime('now')));
"""

# Databases older than this one hold only sample data, so they start again. From this one on, admins add real
# companies, so a database is never dropped: a change to the sample data needs its own change to the database
KEPT_FROM = 5
# name: (email, owner, admin, company). In ZeeSpires, Illia manages three teams and Mike works in two of them; the Support
# Team has its own manager. Northwind is a second, small company, to show that companies don't see each other
USERS = {
    "Dan": ("dan@zeenote.ai", 1, 0, "ZeeSpires"),
    "Illia": ("illia@zeenote.ai", 0, 0, "ZeeSpires"),
    "Mike": ("mike@zeenote.ai", 0, 0, "ZeeSpires"),
    "Lina": ("lina@zeenote.ai", 0, 0, "ZeeSpires"),
    "Noah": ("noah@zeenote.ai", 0, 0, "ZeeSpires"),
    "Yuki": ("yuki@zeenote.ai", 0, 0, "ZeeSpires"),
    "Leo": ("leo@zeenote.ai", 0, 0, "ZeeSpires"),
    "Nora": ("nora@northwind.ai", 1, 0, "Northwind"),
    "Paul": ("paul@northwind.ai", 0, 0, "Northwind"),
    "Olivia": ("olivia@northwind.ai", 0, 0, "Northwind"),
    "Admin": ("admin@zeenote.ai", 0, 1, None),
}
COMPANIES = {
    "ZeeSpires": {
        "Cova Team": [("Illia", "Manager"), ("Mike", "Member"), ("Lina", "Member")],
        "Commity Team": [("Illia", "Manager"), ("Noah", "Member")],
        "AI-Training Team": [("Illia", "Manager"), ("Mike", "Member"), ("Noah", "Member")],
        "Support Team": [("Yuki", "Manager"), ("Leo", "Member")],
    },
    "Northwind": {
        "Sales Team": [("Paul", "Manager"), ("Olivia", "Member")],
    },
}


def default_template() -> dict:
    """
    What a new team starts with: the built-in daily report rules, all turned on, and the usual format.
    """
    return {"rules": [{**rule, "enabled": True} for rule in YamlStore().list_styles()["daily_report"].rules], "layout": asdict(Layout())}


DEFAULT_REPO = "https://github.com/mike1208-dev/zee-note"


def default_settings(reviewer: str = "") -> dict:
    """
    A person's first report settings for a team. They change them on Write report, and the next report starts from those.
    """
    return {"reviewer": reviewer, "first_section": "Yesterday", "done_hours": 8.0, "plan_hours": 8.0, "repo": DEFAULT_REPO, "greeting": GREETING}


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("pragma foreign_keys = on")
    return db


def setup(path: Path = DB_PATH) -> None:
    with connect(path) as db:
        columns = {row[1] for row in db.execute("pragma table_info(users)")}
        if columns and "company_id" not in columns:
            # the first versions, with one sample company and nothing real: start again. Not by the version number, which a
            # database restored from a dump doesn't keep
            names = ("sessions", "reports", "settings", "templates", "members", "teams", "users", "company", "companies")
            db.executescript("".join(f"drop table if exists {name};" for name in names))
        db.executescript(SCHEMA)
        db.execute(f"pragma user_version = {KEPT_FROM}")
        # names that differ only in capitals are the same name
        db.execute("create unique index if not exists company_names on companies (name collate nocase)")
        db.execute("create unique index if not exists team_names on teams (company_id, name collate nocase)")
        # one report a person, team and day: a report copied again replaces that day's one. Copies saved twice before
        # this rule keep only the newest
        db.execute("delete from reports where id not in (select max(id) from reports group by email, team_id, day)")
        db.execute("create unique index if not exists one_report_a_day on reports (email, team_id, day)")
        if db.execute("select count(*) from users").fetchone()[0]:
            return
        ids = {company: db.execute("insert into companies (name) values (?)", (company,)).lastrowid for company in COMPANIES}
        db.executemany(
            "insert into users (email, name, company_id, owner, admin) values (?, ?, ?, ?, ?)",
            [(email, name, ids.get(company), owner, admin) for name, (email, owner, admin, company) in USERS.items()],
        )
        for company, teams in COMPANIES.items():
            for name, people in teams.items():
                team_id = add_team(db, ids[company], name)
                db.executemany("insert into members values (?, ?, ?)", [(team_id, USERS[who][0], role) for who, role in people])


def add_team(db: sqlite3.Connection, company_id: int, name: str) -> int:
    """
    A new team of the company, with the built-in template.
    """
    team_id = db.execute("insert into teams (company_id, name) values (?, ?)", (company_id, name)).lastrowid
    db.execute("insert into templates (team_id, data) values (?, ?)", (team_id, json.dumps(default_template())))
    return team_id
