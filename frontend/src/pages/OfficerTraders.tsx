import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { ErrorNote, Field } from "../components/ui";
import { useT } from "../i18n";
import { useSession } from "../session";

type Trader = { id: number; apmc_code: string; licence_no: string; name: string; firm: string; status: string; status_note: string };
const EMPTY = { licence_no: "", name: "", firm: "", status: "active", status_note: "" };

export default function OfficerTraders() {
  const { t } = useT();
  const { me } = useSession();
  const [list, setList] = useState<Trader[]>([]);
  const [f, setF] = useState(EMPTY);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = () => api.get<Trader[]>("/api/officer/traders").then(setList).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.post("/api/officer/traders", f);
      setF(EMPTY);
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  const shown = list.filter((x) => !q || (x.name + x.licence_no + x.firm).toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {me?.role === "officer" && (
        <form onSubmit={save} className="card space-y-3 md:col-span-1">
          <h2 className="font-bold">Licence register entry</h2>
          <p className="text-xs text-stone-500">Only enter what the APMC's own licence records show. Farmers see this status when they record a sale.</p>
          <Field label={t("trader_licence")}><input className="input" required value={f.licence_no} onChange={(e) => setF({ ...f, licence_no: e.target.value })} /></Field>
          <Field label={t("name")}><input className="input" required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Firm"><input className="input" value={f.firm} onChange={(e) => setF({ ...f, firm: e.target.value })} /></Field>
          <Field label="Licence status">
            <select className="input" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
              <option value="active">Active</option><option value="suspended">Suspended</option><option value="cancelled">Cancelled</option>
            </select>
          </Field>
          <Field label="Order / note"><input className="input" value={f.status_note} onChange={(e) => setF({ ...f, status_note: e.target.value })} /></Field>
          <ErrorNote error={error} />
          <button className="btn-primary w-full">{t("save")}</button>
        </form>
      )}
      <section className="card md:col-span-2">
        <div className="mb-3 flex items-center gap-2">
          <h2 className="font-bold">{t("traders")} ({list.length})</h2>
          <input className="input ml-auto max-w-56" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <ul className="divide-y divide-stone-100">
          {shown.map((x) => (
            <li key={x.id} className="flex flex-wrap items-center gap-2 py-2">
              <div><b>{x.name}</b> <span className="text-sm text-stone-500">{x.firm}</span><div className="text-xs text-stone-500">{x.licence_no}</div></div>
              <span className={`ml-auto rounded-full px-2.5 py-0.5 text-xs font-semibold ${x.status === "active" ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"}`}>{x.status}</span>
              {me?.role === "officer" && <button className="text-sm text-brand-700 underline" onClick={() => setF({ licence_no: x.licence_no, name: x.name, firm: x.firm, status: x.status, status_note: x.status_note })}>edit</button>}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
