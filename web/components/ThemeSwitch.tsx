"use client";

import { useEffect, useState } from "react";
import { Icon, type IconName } from "@/components/Icon";

type Theme = "light" | "dark" | "system";
const KEY = "zeenote-theme";
const THEMES: [Theme, IconName, string][] = [["light", "sun", "Light"], ["dark", "moon", "Dark"], ["system", "monitor", "System"]];

// Light, dark, or the computer's own setting. Kept in this browser; the layout applies it before the page draws
export function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>("system");

  useEffect(() => {
    try {
      const saved = localStorage.getItem(KEY);
      if (saved === "light" || saved === "dark") setTheme(saved);
    } catch {
      // no storage: the computer's setting is used
    }
  }, []);

  function choose(next: Theme) {
    setTheme(next);
    if (next === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = next;
    try {
      if (next === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, next);
    } catch {
      // it still applies until the page is reloaded
    }
  }

  return (
    <div className="segmented theme" role="radiogroup" aria-label="Colours">
      {THEMES.map(([value, icon, label]) => (
        <button key={value} type="button" role="radio" aria-checked={theme === value} title={label} onClick={() => choose(value)}>
          <Icon name={icon} size={13} /> {label}
        </button>
      ))}
    </div>
  );
}
