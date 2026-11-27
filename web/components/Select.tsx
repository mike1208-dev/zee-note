"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Icon } from "@/components/Icon";

export type Option = { value: string; label: string };

// A dropdown in ZeeNote's own look, which the browser's own list can't have. It works with the keyboard as a
// select-only combobox: arrows to move, Enter or Space to pick, Escape to close
export function Select({ value, options, onChange, placeholder = "Choose…", disabled, labelledBy, label, leading, id }: {
  value: string;
  options: Option[];
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  labelledBy?: string;
  label?: string;
  leading?: React.ReactNode;
  id?: string;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [place, setPlace] = useState<React.CSSProperties>({});
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const list = useId();
  const current = options.find((option) => option.value === value);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => !root.current?.contains(event.target as Node) && setOpen(false);
    // the list doesn't follow a scroll of the page, so it closes; scrolling the list itself is fine
    const away = (event: Event) => !root.current?.contains(event.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    window.addEventListener("scroll", away, true);
    window.addEventListener("resize", away);
    return () => {
      document.removeEventListener("mousedown", close);
      window.removeEventListener("scroll", away, true);
      window.removeEventListener("resize", away);
    };
  }, [open]);

  function show() {
    const box = button.current!.getBoundingClientRect();
    const up = window.innerHeight - box.bottom < 280 && box.top > window.innerHeight - box.bottom; // little room below: opens upwards
    setPlace({ left: box.left, width: box.width, ...(up ? { bottom: window.innerHeight - box.top + 6 } : { top: box.bottom + 6 }) });
    setActive(Math.max(0, options.findIndex((option) => option.value === value)));
    setOpen(true);
  }

  function pick(index: number) {
    onChange(options[index].value);
    setOpen(false);
    button.current?.focus();
  }

  function onKeyDown(event: React.KeyboardEvent) {
    const keys: Record<string, () => void> = open
      ? {
          ArrowDown: () => setActive(Math.min(options.length - 1, active + 1)),
          ArrowUp: () => setActive(Math.max(0, active - 1)),
          Home: () => setActive(0),
          End: () => setActive(options.length - 1),
          Enter: () => pick(active),
          " ": () => pick(active),
          Escape: () => setOpen(false),
        }
      : { ArrowDown: show, ArrowUp: show, Enter: show, " ": show };
    if (event.key === "Tab") setOpen(false);
    if (keys[event.key]) {
      event.preventDefault();
      keys[event.key]();
    }
  }

  return (
    <div ref={root} className="select">
      <button ref={button} id={id} type="button" role="combobox" className="select-button" aria-haspopup="listbox" aria-expanded={open} aria-controls={list}
        aria-labelledby={labelledBy} aria-label={label} aria-activedescendant={open ? `${list}-${active}` : undefined} disabled={disabled}
        onClick={() => (open ? setOpen(false) : show())} onKeyDown={onKeyDown}>
        {leading}
        <span className={current?.value ? "" : "faint"} style={{ flex: 1, textAlign: "left", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {current?.value ? current.label : placeholder}
        </span>
        <span className="select-chevron"><Icon name="chevron" size={14} /></span>
      </button>
      {open && (
        <ul id={list} role="listbox" className="select-list" style={place} aria-labelledby={labelledBy} aria-label={label}>
          {options.map((option, i) => (
            <li key={option.value} id={`${list}-${i}`} role="option" aria-selected={option.value === value} className={i === active ? "active" : ""}
              onMouseEnter={() => setActive(i)} onMouseDown={(event) => event.preventDefault()} onClick={() => pick(i)}>
              <span>{option.label}</span>
              {option.value === value && <Icon name="check" size={14} />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
