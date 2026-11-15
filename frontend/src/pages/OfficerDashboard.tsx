import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api, rupees, type ComplaintRow, type TraderRow } from "../api";
import { ErrorNote, Stat } from "../components/ui";
import { useT } from "../i18n";

type Dashboard = {
  apmc_code: string | null; apmc_name: string | null; note: string;
  totals: { sales: number; overdue_amount: number; open_complaints: number; flagged_traders: number };
  traders: TraderRow[]; open_complaints: ComplaintRow[];
};

export default function OfficerDashboard() {
  const { t } = useT();
  const [d, setD] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.get<Dashboard>("/api/officer/dashboard").then(setD).catch((e) => setError(e.message));
  }, []);
  if (!d) return error ? <ErrorNote error={error} /> : <p className="text-stone-500">…</p>;
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold">{d.apmc_name ?? "All APMCs"}</h1>
        <p className="text-sm text-stone-500">{d.note}</p>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label={t("sales_count")} value={d.totals.sales} />
        <Stat label={t("overdue_total")} value={rupees(d.totals.overdue_amount)} tone={d.totals.overdue_amount ? "text-red-700" : ""} />
        <Stat label={t("complaints")} value={d.totals.open_complaints} />
        <Stat label="Flagged traders" value={d.totals.flagged_traders} tone={d.totals.flagged_traders ? "text-red-700" : ""} />
      </div>

      <section className="card">
        <h2 className="mb-3 font-bold">{t("complaints")}</h2>
        {d.open_complaints.length === 0 ? <p className="text-sm text-stone-500">—</p> : (
          <ul className="divide-y divide-stone-100">
            {d.open_complaints.map((c) => (
              <li key={c.id}>
                <Link to={`/officer/complaints/${c.id}`} className="flex flex-wrap items-center gap-2 py-2 hover:bg-stone-50">
                  <b>{c.reference}</b>
                  <span className="text-sm text-stone-500">{c.sale_reference} · {c.created_at.slice(0, 10)}</span>
                  <span className="flex flex-wrap gap-1">{c.categories.map((x) => <span key={x} className="rounded-full bg-amber-100 px-2 py-0.5 text-xs">{t("cat_" + x)}</span>)}</span>
                  <span className="ml-auto rounded-full bg-purple-100 px-2.5 py-0.5 text-xs font-semibold text-purple-800">{c.status.replace("_", " ")}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card overflow-x-auto">
        <h2 className="mb-3 font-bold">{t("traders")}</h2>
        <table className="w-full min-w-[720px] text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-stone-500">
            <tr>
              <th className="py-2">Trader</th><th>Register</th><th className="text-right">Sales</th><th className="text-right">Overdue</th>
              <th className="text-right">Bounced</th><th className="text-right">Weight gaps</th><th className="text-right">Low rate</th><th className="text-right">Complaints</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {d.traders.map((r) => (
              <tr key={r.licence_no + r.name} className={r.flag ? "bg-red-50/60" : ""}>
                <td className="py-2">{r.flag && <span title="Pattern to check" className="mr-1 text-red-600">⚑</span>}<b>{r.name || "—"}</b><div className="text-xs text-stone-500">{r.licence_no || "no licence given"}</div></td>
                <td>{r.registered ? <span className={r.status === "active" ? "text-emerald-700" : "font-semibold text-red-700"}>{r.status}</span> : <span className="text-amber-700">not in register</span>}</td>
                <td className="text-right">{r.sales}</td>
                <td className="text-right">{r.overdue_count ? <span className="text-red-700">{r.overdue_count} · {rupees(r.overdue_amount)}</span> : "0"}</td>
                <td className="text-right">{r.bounced}</td>
                <td className="text-right">{r.weight_gap_sales}</td>
                <td className="text-right">{r.low_rate_sales}</td>
                <td className="text-right">{r.complaints}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
