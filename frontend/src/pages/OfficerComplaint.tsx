import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { api, rupees, type Sale } from "../api";
import { ErrorNote, Field, FindingList, RiskBadge } from "../components/ui";
import { useT } from "../i18n";

type Detail = {
  id: number; reference: string; status: string; categories: string[]; description: string; officer_note: string;
  created_at: string; sale: Sale;
};

export default function OfficerComplaint() {
  const { id } = useParams();
  const { t } = useT();
  const [c, setC] = useState<Detail | null>(null);
  const [status, setStatus] = useState("under_review");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    api.get<Detail>(`/api/officer/complaints/${id}`).then((r) => {
      setC(r);
      setNote(r.officer_note);
      if (r.status !== "submitted") setStatus(r.status);
    }).catch((e) => setError(e.message));
  }, [id]);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const r = await api.patch<{ status: string }>(`/api/officer/complaints/${id}`, { status, officer_note: note });
      setC(c && { ...c, status: r.status, officer_note: note });
      setMsg(t("saved"));
    } catch (err) {
      setError((err as Error).message);
    }
  };
  if (!c) return error ? <ErrorNote error={error} /> : <p className="text-stone-500">…</p>;
  const s = c.sale;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Link to="/officer" className="text-sm text-stone-500">← {t("back")}</Link>
        <h1 className="text-xl font-bold">{c.reference}</h1>
        <span className="rounded-full bg-purple-100 px-2.5 py-0.5 text-xs font-semibold text-purple-800">{c.status.replace("_", " ")}</span>
        <a className="btn-ghost ml-auto" href={`/api/complaints/${c.id}/pack`} target="_blank" rel="noreferrer">🖨 {t("pack")}</a>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <section className="card space-y-2">
          <div className="flex flex-wrap gap-1">{c.categories.map((x) => <span key={x} className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold">{t("cat_" + x)}</span>)}</div>
          <p className="whitespace-pre-wrap">{c.description || "—"}</p>
          <dl className="text-sm">
            <div><dt className="inline text-stone-500">Sale: </dt><dd className="inline"><Link className="underline" to={`/sales/${s.id}`}>{s.reference}</Link> · {s.sale_date}</dd></div>
            <div><dt className="inline text-stone-500">Trader: </dt><dd className="inline">{s.trader_name || "—"} ({s.licence_no || "—"})</dd></div>
            <div><dt className="inline text-stone-500">{t("crop")}: </dt><dd className="inline">{s.crop} · {s.slip_weight_qtl} qtl @ {rupees(s.rate_per_qtl)}</dd></div>
            <div><dt className="inline text-stone-500">{t("net")}: </dt><dd className="inline">{rupees(s.net_amount)} · {t("outstanding")} {rupees(Math.max(0, s.outstanding))}</dd></div>
          </dl>
        </section>
        <section className="card">
          <h2 className="mb-2 flex items-center gap-2 font-bold">{t("checks")} <RiskBadge risk={s.risk} /></h2>
          <FindingList findings={s.findings} />
        </section>
      </div>
      <form onSubmit={save} className="card space-y-3">
        <Field label="Status">
          <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="under_review">Under review</option>
            <option value="resolved">Resolved</option>
            <option value="rejected">Rejected</option>
          </select>
        </Field>
        <Field label="Note to farmer" hint="The farmer sees this note in their notifications.">
          <textarea className="input min-h-24" maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <ErrorNote error={error} />
        {msg && <p className="text-sm text-emerald-700">{msg}</p>}
        <button className="btn-primary">{t("save")}</button>
      </form>
    </div>
  );
}
