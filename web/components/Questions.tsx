"use client";

import type { Ask } from "@/lib/api";
import { Icon } from "@/components/Icon";
import { Select } from "@/components/Select";

const rowsOf = (ask: Ask) => (ask.items.length ? ask.items : [""]);

// A status is picked, so it's always a word the checker knows
const CHOICES: Record<string, string[]> = {
  "What is the status (Done or In progress)?": ["Done", "In progress"],
  "What is the status of the PR (for example Merged or In review)?": ["Merged", "In review", "Draft", "Open", "Closed"],
};

// The answers written as notes, "item: answer". An empty box is skipped
export function answersAsNotes(asks: Ask[], answers: Record<string, string>): string[] {
  return asks.flatMap((ask, i) =>
    rowsOf(ask).flatMap((item, j) => {
      const answer = answers[`${i}-${j}`]?.trim();
      return answer ? [item ? `${item}: ${answer}` : answer] : [];
    }),
  );
}

// Each item of a question has its own box. "open" is what the written report still asks, or null before it's written
export function Questions({ asks, answers, onAnswer, open, disabled, writing, onWrite }: {
  asks: Ask[];
  answers: Record<string, string>;
  onAnswer: (key: string, value: string) => void;
  open: Ask[] | null;
  disabled: boolean;
  writing: boolean;
  onWrite: () => void;
}) {
  const solved = (ask: Ask, item: string) => open !== null && !open.some((other) => other.ask === ask.ask && (!item || other.items.includes(item)));
  const done = open !== null && open.length === 0;
  const count = asks.reduce((sum, ask) => sum + rowsOf(ask).length, 0);

  return (
    <section id="questions" className={`card flush questions ${done ? "done" : ""}`} aria-live="polite">
      <div className="card-head">
        <div className="title-row">
          <span className="badge-num">2</span>
          <div>
            <h2>{count === 1 ? "1 question" : `${count} questions`}</h2>
            <p className="soft small">Leave one empty to skip it. Changed your notes? Click Check notes again.</p>
          </div>
        </div>
        {done && <span className="tag ok"><Icon name="check" size={12} /> All answered</span>}
      </div>
      {/* the part of the notes first, then the question about it; not a label, so a click on the words opens nothing.
          Many questions scroll inside the card, so Write report stays in reach */}
      <div className="question-list" tabIndex={-1}>
      {asks.map((ask, i) =>
        rowsOf(ask).map((item, j) => (
          <div key={`${i}-${j}`} className="question">
            {item && <span className="from">{item}</span>}
            <span id={`ask-${i}-${j}`} className="ask">
              {ask.ask}
              {solved(ask, item) && <span className="solved" aria-label="Answered"><Icon name="check" size={14} /></span>}
            </span>
            {CHOICES[ask.ask] ? (
              <Select labelledBy={`ask-${i}-${j}`} value={answers[`${i}-${j}`] ?? ""} onChange={(value) => onAnswer(`${i}-${j}`, value)} disabled={disabled}
                options={[{ value: "", label: "Skip" }, ...CHOICES[ask.ask].map((choice) => ({ value: choice, label: choice }))]} />
            ) : (
              <input aria-labelledby={`ask-${i}-${j}`} value={answers[`${i}-${j}`] ?? ""} onChange={(event) => onAnswer(`${i}-${j}`, event.target.value)} disabled={disabled}
                onKeyDown={(event) => event.key === "Enter" && event.preventDefault()} /* Enter would check the notes again */ />
            )}
          </div>
        )),
      )}
      </div>
      <div className="card-foot">
        <span className="faint small">Your answers are added to your notes.</span>
        <button type="button" className="btn main" onClick={onWrite} disabled={disabled}>
          {writing ? "Writing…" : <>Write report <Icon name="arrow" size={14} /></>}
        </button>
      </div>
    </section>
  );
}
