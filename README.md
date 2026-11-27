# ZeeNote

**Plain notes in, a daily report your team can trust out.**

ZeeNote turns a team member's rough notes into a daily report in the team's own format. It checks every fact against the
notes, asks about anything that is missing or doubtful, and never makes things up. The goal is to run it on **our own trained
AI**: a small model that sorts notes into the parts of a report, so notes can stay inside the company with no daily limit.

> Some files still use the earlier name, ZeeChecker.

## Features

- **Write a report in three steps:** write notes in any order → answer a few short questions about what's missing → get the
  finished report, shown as the Slack message it becomes, and copy it for Slack.
- **The team's own template and rules:** managers rename the report's sections, turn icons, hours, links and the greeting
  on or off with a live preview, and turn rules on or off or add their own AI rules.
- **Many companies:** each company sees only its own people, teams and reports. Owners add teams and people; a ZeeNote admin
  adds companies and sees numbers only, never reports.
- **My reports:** one report per person, team and day, grouped by month, to read again, copy or delete.
- **Light and dark**, keyboard friendly, and works on a phone.

## How it works

```
rough notes ──► AI sorts them into fields ──► code checks every field ──► questions about ──► code writes the report
                (tasks, statuses, PRs,        against the notes            what's missing      in the team's format,
                 plans, blockers)                                                              then checks the rules
```

**The main rule:** the AI only sorts the notes. Code writes the report, so the format is always the same, and a status, link
or number that the notes don't support is left out or asked about.

### Example

Notes:

```text
issue 95 fix booking list shows the wrong date, pr 102 merged
practiced the project presentation
today: issue 97 chore add validation to the password reset form
blocker: waiting for QA validation on staging
```

ZeeNote asks: *Practiced the project presentation: what is the status (Done or In progress)?* After the answer:

```text
✅ Yesterday (8 hours)
    issue-95 ― [FIX] Booking list shows the wrong date
        https://github.com/acme/app/pull/102 ― Merged
    Practiced the project presentation ― Done
🎯 Today (8 hours)
    issue-97 ― [CHORE] Add validation to the password reset form
🚧 Blockers / 📝 Notes
    Waiting for QA validation on staging
```

## Tech stack

| Part | Built with |
| --- | --- |
| Web app | Next.js 16, React 19, TypeScript (`web/`) |
| API | FastAPI, SQLite (`api/`) |
| Report writer and checks | Python (`checker/`) |
| AI | [Groq](https://console.groq.com) for now; our own model trained with LoRA in Google Colab (`training/`) |

## Quick start

Needs **Python 3.11** and **Node.js 20.9 or newer**. The commands are for Windows (Command Prompt); on macOS or Linux use
`source .venv/bin/activate` and `cp` instead.

```cmd
git clone https://github.com/mike1208-dev/zee-note.git
cd zee-note
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
notepad .env
cd web
npm install
```

In `.env`, put a Groq key after `GROQ_API_KEY=` (free key: https://console.groq.com/keys), and a password of your own after
`ZEENOTE_PASSWORD=`. **Never commit `.env` or share a key.**

Run the API and the web app, each in its own window:

```cmd
.venv\Scripts\python -m uvicorn api.main:app --reload
```

```cmd
cd web
npm run dev
```

Open http://localhost:3000 and sign in with a sample account. Every account uses the `ZEENOTE_PASSWORD` from `.env`
(`zeenote` if it isn't set; the ZeeNote admin needs it set).

| Account | Role | Can do |
| --- | --- | --- |
| `dan@zeenote.ai` | Company owner | Every team's template and rules; the company's name, teams and people |
| `illia@zeenote.ai` | Team manager of three teams | Write reports; their teams' template and rules |
| `mike@zeenote.ai` | Team member of two teams | Write reports, see their own reports |
| `admin@zeenote.ai` | ZeeNote admin | Every company's numbers, never its reports; adding a company |

The sample companies are made the first time the API starts, in `data/zeenote.db`. To start again from nothing, stop the
API and delete that file.

### Share it for a trial

A [Cloudflare quick tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/)
gives the app on your computer a public `https://….trycloudflare.com` address while your computer and three windows are on:

```cmd
.venv\Scripts\python -m uvicorn api.main:app
```

```cmd
cd web
npm run build
npm start
```

```cmd
cloudflared tunnel --url http://localhost:3000
```

Limits to know:

- **One password for everyone.** v1 has no real accounts: every sample person signs in with the same `ZEENOTE_PASSWORD`.
  Share the link only with people you trust, send the password privately, and change it after a trial. A sign-in lasts two
  weeks, and ten wrong passwords for one email make it wait 15 minutes.
- Everything people write goes to Groq with the key in `.env`, and they share its daily limit.
- `ZEENOTE_API_URL` (where the web app finds the API) is read by `npm run build`, not by `npm start`.
- A quick tunnel cuts a request after about 100 seconds. If the AI is slow, writing a report can fail with "Something went
  wrong (524)"; trying again usually works.

## Project layout

| Path | Purpose |
| --- | --- |
| `web/app/` | The pages: sign in, Write report, My reports, Template and rules, Settings, the admin overview |
| `web/components/`, `web/lib/` | Shared parts (menu, dropdown, questions, theme switch) and the API client and session |
| `api/main.py` | The API: sign-in, companies, teams and people, templates and rules, writing and saving reports |
| `api/db.py` | The SQLite database and the sample companies |
| `checker/writer.py` | Asks the AI for the fields, checks them against the notes, asks about gaps, and writes the report |
| `checker/statuses.py` | Finds which statuses and PR or issue numbers the notes support |
| `checker/markup.py` | The report's Markdown as HTML (preview) and in Slack's format (copy) |
| `checker/report.py`, `basic_checks.py`, `llm_checks.py`, `validation.py` | Runs the rules, by code and by AI, and checks rules before they're saved |
| `rules/*.yaml` | The built-in rules |
| `training/` | Made-up notes with known answers, scoring, and the Colab training notebook |
| `tests/` | pytest tests, with stand-ins for the AI: no API key or network needed |
| `app.py`, `views/` | The first prototype, in Streamlit (see below) |

## Tests

```cmd
.venv\Scripts\python -m pytest -q
cd web
npm run type-check
```

## Report rules

| Rule | Checked by | A report passes when… |
| --- | --- | --- |
| `has_sections` | code | It has the team's sections: Yesterday (or Weekend), Today, and Blockers / Notes |
| `tags_reviewer` | code | It tags the reviewer at the top |
| `has_hours` | code | It gives hours for both Yesterday and Today |
| `concrete_tasks` | AI | Each task says what was done or will be done |
| `status_or_result` | AI | Each finished task has a status or result |
| `clear_and_short` | AI | It is easy to read, with no repeated lines or needless detail |
| `terms_explained` | AI | New, advanced or internal terms are explained |
| `real_blockers` | AI | Blockers are stated clearly, or "None" when there are none |

A team can have up to 40 rules, 10 of them AI rules: each AI rule is one call to the AI for every report.

## Our own AI

The model has one job: rough notes in, the parts of a report out, as JSON. A small model can learn one job well, and it can
run on our own server.

1. **Training data:** code makes rough notes from fields it chose first, so every answer is known and no AI writes them.
   Typos, mixed order, emojis, missing parts and Japanese words are added on purpose.
2. **Training:** a LoRA fine-tune of Qwen2.5-1.5B-Instruct in Google Colab (free T4 GPU): open `training/notes_lora.ipynb`,
   choose **Runtime → Change runtime type → T4 GPU**, and run the cells from top to bottom.
3. **Scoring:** the app's own code scores the model before and after training:
   `python -m training.score_notes --name <name> --gguf <model file>`, or `--groq <model>`.

| Goal | Value |
| --- | --- |
| Reports with a wrong fact and no warning | At most 2 of 100 |
| Right fields | Within 5 points of the best cloud model |
| Time per report on our own server | Under 30 seconds |

## The Streamlit prototype

The first version runs as a single Streamlit page: `.venv\Scripts\python -m streamlit run app.py`, then open
http://localhost:8501. Its rules can come from a Supabase database (`SUPABASE_URL`, `SUPABASE_KEY`, `EDITOR_PASSWORD` in
`.env`, tables in `supabase/migrations/`), or from `rules/*.yaml` without one. The cloud models are set in `.env`
(`GROQ_MODEL`, `GROQ_MODELS`); see `.env.example`.

## Privacy

- Notes and reports are sent to the AI service while a cloud AI is used. The page says so.
- Text that looks like a key or a password is never sent to the AI.
- Only made-up notes are used for training in the cloud. Real reports and notes stay private: keep them in `data/`, which Git
  ignores, never in this repository.

## Contributing

- Start each piece of work from a GitHub issue titled `[TYPE] Short description` (`[FIX]`, `[FEAT]`, `[REFACTOR]`,
  `[CHORE]`), with a `## What` checklist and a `## DoD` checklist.
- Work on a branch from `develop` named `type/issue-<number>-short-description`, such as `fix/issue-12-date-after-page-change`.
- Commit messages are one line, such as `feat: add the team feed` or `fix: keep the date after another page`.
- Never push directly to `main` or `develop`: every change goes through a pull request into `develop`.
- Pull request titles use the same style as commits. The description has `## What changed` and `## How tested` (say plainly
  what you couldn't test), and ends with `Closes #<issue>`, or `Part of #<issue>` when it does only part of it.
- Run the tests and the type check before opening a pull request.
