import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api, rupees, type Sale } from "../api";
import { ErrorNote, RiskBadge, Stat, StatusChip } from "../components/ui";
import { useT } from "../i18n";

export default function Sales() {
  const { t } = useT();
  const [sales, setSales] = useState<Sale[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.get<Sale[]>("/api/sales").then(setSales).catch((e) => setError(e.message));
  }, []);
  if (error) return <ErrorNote error={error} />;
  if (!sales) return <p className="text-stone-500">…</p>;
  const outstanding = sales.reduce((a, s) => a + Math.max(0, s.outstanding), 0);
  const overdue = sales.filter((s) => s.status === "overdue" || s.status === "bounced").reduce((a, s) => a + s.outstanding, 0);
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label={t("sales_count")} value={sales.length} />
        <Stat label={t("outstanding")} value={rupees(outstanding)} />
        <Stat label={t("overdue_total")} value={rupees(overdue)} tone={overdue > 0 ? "text-red-700" : ""} />
        <Stat label={t("high_risk")} value={sales.filter((s) => s.risk === "high").length} tone="text-red-700" />
      </div>
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">{t("my_sales")}</h1>
        <Link to="/sales/new" className="btn-primary">+ {t("new_sale")}</Link>
      </div>
      {sales.length === 0 ? (
        <p className="card text-stone-600">{t("no_sales")}</p>
      ) : (
        <ul className="space-y-3">
          {sales.map((s) => {
            const top = s.findings.find((f) => f.severity === "high") ?? s.findings.find((f) => f.severity === "medium");
            return (
              <li key={s.id}>
                <Link to={`/sales/${s.id}`} className="card block transition hover:ring-brand-600">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-bold">{s.crop} {s.variety}</span>
                    <span className="text-sm text-stone-500">· {s.slip_weight_qtl} qtl · {rupees(s.rate_per_qtl)}/qtl</span>
                    <span className="ml-auto flex gap-2"><StatusChip status={s.status} /><RiskBadge risk={s.risk} /></span>
                  </div>
                  <div className="mt-1 text-sm text-stone-600">
                    {s.sale_date} · {s.apmc_name} · {s.trader_name || s.licence_no || "—"}
                  </div>
                  <div className="mt-2 flex flex-wrap items-baseline gap-x-4 text-sm">
                    <span>{t("net")}: <b>{rupees(s.net_amount)}</b></span>
                    {s.outstanding > 0 && <span className="text-red-700">{t("outstanding")}: <b>{rupees(s.outstanding)}</b></span>}
                  </div>
                  {top && <p className="mt-2 line-clamp-2 text-sm text-stone-700">⚠ {top.message}</p>}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
