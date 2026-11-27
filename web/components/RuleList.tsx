import type { RuleResult } from "@/lib/api";
import { Icon } from "@/components/Icon";

const MARKS: Record<RuleResult["status"], string> = { PASS: "ok", FAIL: "bad", WARN: "warn", SKIP: "off" };

export function RuleList({ rules }: { rules: RuleResult[] }) {
  return (
    <ul className="rules">
      {rules.map((rule, i) => (
        <li key={`${rule.id}-${i}`}>
          <span className={`tag ${MARKS[rule.status]}`} style={{ padding: 3 }} aria-label={rule.status}>
            <Icon name={rule.status === "PASS" ? "check" : rule.status === "SKIP" ? "next" : "alert"} size={11} />
          </span>
          <span className={rule.status === "PASS" ? "" : "soft"}>{rule.title}</span>
        </li>
      ))}
    </ul>
  );
}
