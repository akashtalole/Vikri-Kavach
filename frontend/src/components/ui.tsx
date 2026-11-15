import type { ReactNode } from "react";
import type { Finding } from "../api";
import { useT } from "../i18n";

const sevStyle: Record<string, string> = {
  high: "bg-red-50 text-red-900 ring-red-200",
  medium: "bg-amber-50 text-amber-900 ring-amber-200",
  info: "bg-sky-50 text-sky-900 ring-sky-200",
  ok: "bg-emerald-50 text-emerald-900 ring-emerald-200",
};
const sevIcon: Record<string, string> = { high: "⚠", medium: "!", info: "i", ok: "✓" };

export function FindingList({ findings }: { findings: Finding[] }) {
  return (
    <ul className="space-y-2">
      {findings.map((f, i) => (
        <li key={i} className={`flex gap-3 rounded-xl p-3 text-sm ring-1 ${sevStyle[f.severity]}`}>
          <span aria-hidden className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-white/70 font-bold">
            {sevIcon[f.severity]}
          </span>
          <span>{f.message}</span>
        </li>
      ))}
    </ul>
  );
}

export function RiskBadge({ risk }: { risk: string }) {
  const { t } = useT();
  const s = risk === "high" ? "bg-red-600 text-white" : risk === "medium" ? "bg-amber-400 text-amber-950" : "bg-emerald-600 text-white";
  return <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${s}`}>{t("risk_" + risk)}</span>;
}

export function StatusChip({ status }: { status: string }) {
  const { t } = useT();
  const s =
    status === "paid" ? "bg-emerald-100 text-emerald-800"
      : status === "overdue" || status === "bounced" ? "bg-red-100 text-red-800"
      : status === "disputed" ? "bg-purple-100 text-purple-800"
      : "bg-stone-100 text-stone-700";
  return <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${s}`}>{t("status_" + status)}</span>;
}

export function Stat({ label, value, tone = "" }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className="card">
      <div className="text-xs font-semibold uppercase tracking-wide text-stone-500">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${tone}`}>{value}</div>
    </div>
  );
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800 ring-1 ring-red-200">{error}</p>;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-stone-500">{hint}</span>}
    </label>
  );
}
