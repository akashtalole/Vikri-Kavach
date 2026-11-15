import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { api, rupees, today, type Sale } from "../api";
import { ErrorNote, Field, FindingList, RiskBadge, StatusChip } from "../components/ui";
import { useT } from "../i18n";
import { useSession } from "../session";

const EVIDENCE = ["patti", "weighbridge", "cheque", "produce", "other"];

export default function SaleDetail() {
  const { id } = useParams();
  const { t } = useT();
  const { me, ref } = useSession();
  const [s, setS] = useState<Sale | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [kind, setKind] = useState("patti");
  const [pay, setPay] = useState({ kind: "received", amount: "", on_date: today(), note: "" });
  const [cats, setCats] = useState<string[]>([]);
  const [desc, setDesc] = useState("");
  const farmer = me?.role === "farmer";

  useEffect(() => {
    api.get<Sale>(`/api/sales/${id}`).then(setS).catch((e) => setError(e.message));
  }, [id]);

  const act = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const upload = (file: File) => act(async () => {
    const fd = new FormData();
    fd.append("kind", kind);
    fd.append("file", file);
    setS(await api.post<Sale>(`/api/sales/${id}/evidence`, fd));
  });
  const addPayment = (e: FormEvent) => {
    e.preventDefault();
    act(async () => {
      setS(await api.post<Sale>(`/api/sales/${id}/payments`, { ...pay, amount: Number(pay.amount) || 0 }));
      setPay({ ...pay, amount: "", note: "" });
    });
  };
  const complain = (e: FormEvent) => {
    e.preventDefault();
    act(async () => {
      await api.post(`/api/sales/${id}/complaint`, { categories: cats, description: desc });
      setS(await api.get<Sale>(`/api/sales/${id}`));
    });
  };

  if (!s) return error ? <ErrorNote error={error} /> : <p className="text-stone-500">…</p>;
  const suggested = new Set(
    s.findings.flatMap((f) =>
      f.code === "weight_gap" ? ["weight"] : f.code.startsWith("rate_") && f.code !== "rate_ok" ? ["rate"]
        : f.code === "payment_overdue" ? ["payment_delay"] : f.code === "cheque_bounced" ? ["cheque_bounced"]
        : f.code.startsWith("trader_") ? ["unlicensed_trader"] : f.code.endsWith("_math") || f.code.startsWith("high_") || f.code.startsWith("not_allowed_") ? ["deductions"] : []),
  );
  const rows: [string, string][] = [
    [t("apmc"), `${s.apmc_name} · ${s.market_name}`],
    [t("trader_name"), `${s.trader_name || "—"} (${s.licence_no || "—"}) · ${s.trader_registered ? t("registered") + ": " + s.trader_status : t("not_registered")}`],
    [t("crop"), `${s.crop} ${s.variety}`],
    [t("slip_weight"), `${s.slip_weight_qtl}${s.own_weight_qtl ? ` · ${t("own_weight")}: ${s.own_weight_qtl}` : ""}${s.bags ? ` · ${t("bags")}: ${s.bags}` : ""}`],
    [t("rate"), rupees(s.rate_per_qtl)],
    [t("gross"), rupees(s.gross_amount)],
    [t("deductions"), s.deductions.map((d) => `${d.label || d.kind} ${rupees(d.amount)}`).join(", ") || "—"],
    [t("net"), rupees(s.net_amount)],
    [t("payment_mode"), t("mode_" + s.payment_mode)],
    [t("payment_due"), s.payment_due],
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Link to={farmer ? "/" : "/officer"} className="text-sm text-stone-500">← {t("back")}</Link>
        <h1 className="text-xl font-bold">{s.reference}</h1>
        <StatusChip status={s.status} />
        <RiskBadge risk={s.risk} />
        <span className="ml-auto text-sm text-stone-500">{s.sale_date}</span>
      </div>

      <div className="grid gap-4 md:grid-cols-5">
        <section className="card md:col-span-3">
          <h2 className="mb-3 font-bold">{t("checks")}</h2>
          <FindingList findings={s.findings} />
        </section>
        <section className="card md:col-span-2">
          <div className="grid grid-cols-2 gap-2 text-center">
            <div className="rounded-xl bg-stone-100 p-3"><div className="text-xs text-stone-500">{t("net")}</div><div className="text-xl font-bold">{rupees(s.net_amount)}</div></div>
            <div className={`rounded-xl p-3 ${s.outstanding > 0 ? "bg-red-50" : "bg-emerald-50"}`}>
              <div className="text-xs text-stone-500">{t("outstanding")}</div>
              <div className={`text-xl font-bold ${s.outstanding > 0 ? "text-red-700" : "text-emerald-700"}`}>{rupees(Math.max(0, s.outstanding))}</div>
            </div>
          </div>
          <dl className="mt-3 divide-y divide-stone-100 text-sm">
            {rows.map(([k, v]) => (
              <div key={k} className="grid grid-cols-[40%_60%] gap-2 py-1.5"><dt className="text-stone-500">{k}</dt><dd className="break-words">{v}</dd></div>
            ))}
          </dl>
        </section>
      </div>

      <section className="card space-y-3">
        <h2 className="font-bold">{t("evidence")}</h2>
        <div className="flex flex-wrap gap-3">
          {s.evidence.map((e) => (
            <a key={e.id} href={`/api/evidence/${e.id}`} target="_blank" rel="noreferrer" className="w-28 text-center text-xs">
              {e.content_type.startsWith("image/")
                ? <img src={`/api/evidence/${e.id}`} alt={e.kind} className="h-24 w-28 rounded-lg object-cover ring-1 ring-stone-200" />
                : <div className="grid h-24 w-28 place-items-center rounded-lg bg-stone-100 ring-1 ring-stone-200">PDF</div>}
              {t("kind_" + e.kind)}
            </a>
          ))}
        </div>
        {farmer && (
          <div className="flex flex-wrap gap-2">
            <select className="input w-auto" value={kind} onChange={(e) => setKind(e.target.value)}>
              {EVIDENCE.map((k) => <option key={k} value={k}>{t("kind_" + k)}</option>)}
            </select>
            <label className="btn-ghost cursor-pointer">
              📎 {t("add_photo")}
              <input type="file" accept="image/*,application/pdf" className="hidden" disabled={busy}
                onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            </label>
          </div>
        )}
      </section>

      <section className="card space-y-3">
        <h2 className="font-bold">{t("payments")}</h2>
        {s.payments.length > 0 && (
          <ul className="space-y-1 text-sm">
            {s.payments.map((p, i) => (
              <li key={i} className="flex gap-2"><span className="text-stone-500">{p.on_date}</span><b>{t(p.kind)}</b>{rupees(p.amount)}<span className="text-stone-500">{p.note}</span></li>
            ))}
          </ul>
        )}
        {farmer && s.status !== "paid" && (
          <form onSubmit={addPayment} className="grid gap-2 md:grid-cols-5">
            <select className="input" value={pay.kind} onChange={(e) => setPay({ ...pay, kind: e.target.value })}>
              {["received", "cheque_bounced", "promised"].map((k) => <option key={k} value={k}>{t(k)}</option>)}
            </select>
            <input className="input" type="number" min="0" step="0.01" placeholder={t("amount")} value={pay.amount} onChange={(e) => setPay({ ...pay, amount: e.target.value })} />
            <input className="input" type="date" max={today()} value={pay.on_date} onChange={(e) => setPay({ ...pay, on_date: e.target.value })} />
            <input className="input" placeholder={t("note")} value={pay.note} onChange={(e) => setPay({ ...pay, note: e.target.value })} />
            <button className="btn-primary" disabled={busy}>{t("record_payment")}</button>
          </form>
        )}
      </section>

      <section className="card space-y-3">
        <h2 className="font-bold">{t("complaint")}</h2>
        {s.complaint ? (
          <div className="space-y-2">
            <p className="flex flex-wrap items-center gap-2">
              <b>{s.complaint.reference}</b>
              <span className="rounded-full bg-purple-100 px-2.5 py-0.5 text-xs font-semibold text-purple-800">{s.complaint.status.replace("_", " ")}</span>
            </p>
            {s.complaint.officer_note && <p className="rounded-xl bg-stone-100 p-3 text-sm">{s.complaint.officer_note}</p>}
            <a className="btn-ghost" href={`/api/complaints/${s.complaint.id}/pack`} target="_blank" rel="noreferrer">🖨 {t("pack")}</a>
          </div>
        ) : farmer ? (
          <form onSubmit={complain} className="space-y-3">
            <div className="flex flex-wrap gap-2">
              {(ref?.complaint_categories ?? []).map((c) => {
                const on = cats.includes(c);
                return (
                  <button type="button" key={c} onClick={() => setCats(on ? cats.filter((x) => x !== c) : [...cats, c])}
                    className={`rounded-full px-3 py-1.5 text-sm font-semibold ring-1 ${on ? "bg-brand-700 text-white ring-brand-700" : suggested.has(c) ? "bg-amber-50 ring-amber-300" : "bg-white ring-stone-300"}`}>
                    {t("cat_" + c)}
                  </button>
                );
              })}
            </div>
            <Field label={t("describe")}>
              <textarea className="input min-h-24" maxLength={2000} value={desc} onChange={(e) => setDesc(e.target.value)} />
            </Field>
            <button className="btn-danger" disabled={busy || cats.length === 0}>{t("raise_complaint")}</button>
          </form>
        ) : <p className="text-sm text-stone-500">—</p>}
      </section>
      <ErrorNote error={error} />
    </div>
  );
}
