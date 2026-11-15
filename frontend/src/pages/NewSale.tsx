import { useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { api, rupees, today, type Deduction, type Sale } from "../api";
import { ErrorNote, Field } from "../components/ui";
import { useT } from "../i18n";
import { useSession } from "../session";

type Lookup = { licence_no: string; name: string; firm: string; status: string; status_note: string }[];
type SlipRead = {
  readable: boolean; market: string; sale_date: string; trader_or_agent: string; commodity: string;
  lines: { quantity_qtl: number; rate_per_qtl: number; amount: number }[]; gross_amount: number;
  deductions: Deduction[]; net_paid: number; payment_mode: string; illegible_parts: string;
};
const KINDS = ["commission", "hamali", "weighing", "market_fee", "transport", "advance_recovery", "other"];
const MODES = ["not_stated", "cash", "cheque", "bank_transfer", "upi"];
const num = (v: string) => (v === "" ? null : Number(v));

export default function NewSale() {
  const { t, lang } = useT();
  const { me, ref } = useSession();
  const nav = useNavigate();
  const [f, setF] = useState({
    apmc_code: me?.apmc_code ?? "", market_name: "", licence_no: "", trader_name: "", commodity_code: "08035",
    variety: "", bags: "", own_weight_qtl: "", slip_weight_qtl: "", rate_per_qtl: "", gross_amount: "", net_amount: "",
    payment_mode: "not_stated", sale_date: today(), payment_due: "",
  });
  const [deds, setDeds] = useState<Deduction[]>([]);
  const [slipFile, setSlipFile] = useState<File | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [lookup, setLookup] = useState<Lookup | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  const byDistrict = useMemo(() => {
    const m = new Map<string, NonNullable<typeof ref>["apmcs"]>();
    for (const a of ref?.apmcs ?? []) m.set(a.district, [...(m.get(a.district) ?? []), a]);
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [ref]);

  const calcGross = (Number(f.slip_weight_qtl) || 0) * (Number(f.rate_per_qtl) || 0);
  const dedTotal = deds.reduce((a, d) => a + (Number(d.amount) || 0), 0);
  const gross = f.gross_amount === "" ? calcGross : Number(f.gross_amount);
  const net = f.net_amount === "" ? gross - dedTotal : Number(f.net_amount);

  const readSlip = async (file: File) => {
    setSlipFile(file);
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api.post<SlipRead>("/api/slips/read", fd);
      const qty = r.lines.reduce((a, l) => a + (l.quantity_qtl || 0), 0);
      const rate = r.lines[0]?.rate_per_qtl || 0;
      const crop = ref?.crops.find((c) => r.commodity && (r.commodity.includes(c.mr) || c.en.toLowerCase().includes(r.commodity.toLowerCase())));
      setF((p) => ({
        ...p, trader_name: r.trader_or_agent || p.trader_name, market_name: r.market || p.market_name,
        commodity_code: crop?.code ?? p.commodity_code, slip_weight_qtl: qty ? String(+qty.toFixed(3)) : p.slip_weight_qtl,
        rate_per_qtl: rate ? String(rate) : p.rate_per_qtl, gross_amount: r.gross_amount ? String(r.gross_amount) : p.gross_amount,
        net_amount: r.net_paid ? String(r.net_paid) : p.net_amount, payment_mode: MODES.includes(r.payment_mode) ? r.payment_mode : p.payment_mode,
        sale_date: /^\d{4}-\d{2}-\d{2}$/.test(r.sale_date) ? r.sale_date : p.sale_date,
      }));
      setDeds(r.deductions);
      setInfo(t("slip_read_ok") + (r.illegible_parts ? ` (${r.illegible_parts})` : ""));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const checkTrader = async () => {
    if (!f.apmc_code || !f.licence_no) return;
    try {
      const r = await api.get<Lookup>(`/api/traders/lookup?apmc_code=${encodeURIComponent(f.apmc_code)}&licence_no=${encodeURIComponent(f.licence_no)}`);
      setLookup(r);
      if (r[0] && !f.trader_name) setF((p) => ({ ...p, trader_name: r[0].name }));
    } catch {
      setLookup(null);
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const sale = await api.post<Sale>("/api/sales", {
        ...f, bags: num(f.bags), own_weight_qtl: num(f.own_weight_qtl), slip_weight_qtl: Number(f.slip_weight_qtl),
        rate_per_qtl: Number(f.rate_per_qtl), gross_amount: +gross.toFixed(2), net_amount: +net.toFixed(2),
        deductions: deds.filter((d) => d.label || d.amount).map((d) => ({ ...d, amount: Number(d.amount) || 0 })),
        payment_due: f.payment_due || null,
      });
      if (slipFile) {
        const fd = new FormData();
        fd.append("kind", "patti");
        fd.append("file", slipFile);
        await api.post(`/api/sales/${sale.id}/evidence`, fd).catch(() => {});
      }
      nav(`/sales/${sale.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <h1 className="text-xl font-bold">{t("new_sale")}</h1>

      {ref?.ai_slip_reading && <section className="card space-y-2 bg-brand-50">
        <label className="btn-primary w-full cursor-pointer">
          📷 {busy ? t("reading") : t("read_slip")}
          <input type="file" accept="image/*,application/pdf" capture="environment" className="hidden"
            onChange={(e) => e.target.files?.[0] && readSlip(e.target.files[0])} />
        </label>
        {info && <p className="text-sm text-brand-900">{info}</p>}
      </section>}

      <section className="card grid gap-3 md:grid-cols-2">
        <Field label={t("apmc")}>
          <select className="input" required value={f.apmc_code} onChange={(e) => {
            const a = ref?.apmcs.find((x) => x.code === e.target.value);
            const stem = (a?.name_mr ?? "").split(/[\s(]/)[0].replace(/ं/g, "");
            const m = ref?.price_markets.find((p) => stem && p.replace(/ं/g, "").startsWith(stem));
            setF({ ...f, apmc_code: e.target.value, market_name: f.market_name || m || "" });
          }}>
            <option value="">—</option>
            {byDistrict.map(([d, list]) => (
              <optgroup key={d} label={d}>
                {list.map((a) => <option key={a.code} value={a.code}>{lang === "mr" ? a.name_mr : a.name_en}</option>)}
              </optgroup>
            ))}
          </select>
        </Field>
        <Field label={t("market")}>
          <input className="input" list="markets" required value={f.market_name} onChange={set("market_name")} />
          <datalist id="markets">{ref?.price_markets.map((m) => <option key={m} value={m} />)}</datalist>
        </Field>
        <Field label={t("trader_licence")}>
          <div className="flex gap-2">
            <input className="input" value={f.licence_no} onChange={(e) => { set("licence_no")(e); setLookup(null); }} onBlur={checkTrader} />
            <button type="button" className="btn-ghost" onClick={checkTrader}>{t("lookup")}</button>
          </div>
          {lookup && (
            lookup.length ? (
              <span className={`mt-1 block text-sm font-semibold ${lookup[0].status === "active" ? "text-emerald-700" : "text-red-700"}`}>
                ✓ {t("registered")}: {lookup[0].name} — {lookup[0].status} {lookup[0].status_note}
              </span>
            ) : <span className="mt-1 block text-sm font-semibold text-amber-700">⚠ {t("not_registered")}</span>
          )}
        </Field>
        <Field label={t("trader_name")}>
          <input className="input" value={f.trader_name} onChange={set("trader_name")} />
        </Field>
        <Field label={t("crop")}>
          <select className="input" value={f.commodity_code} onChange={set("commodity_code")}>
            {ref?.crops.map((c) => <option key={c.code} value={c.code}>{lang === "mr" ? c.mr : c.en}</option>)}
          </select>
        </Field>
        <Field label={`${t("variety")} (${t("optional")})`}>
          <input className="input" value={f.variety} onChange={set("variety")} />
        </Field>
      </section>

      <section className="card grid gap-3 md:grid-cols-3">
        <Field label={t("own_weight")}>
          <input className="input" type="number" step="0.001" min="0" inputMode="decimal" value={f.own_weight_qtl} onChange={set("own_weight_qtl")} />
        </Field>
        <Field label={t("slip_weight")}>
          <input className="input" type="number" step="0.001" min="0" inputMode="decimal" required value={f.slip_weight_qtl} onChange={set("slip_weight_qtl")} />
        </Field>
        <Field label={`${t("bags")} (${t("optional")})`}>
          <input className="input" type="number" min="0" inputMode="numeric" value={f.bags} onChange={set("bags")} />
        </Field>
        <Field label={t("rate")}>
          <input className="input" type="number" step="0.01" min="0" inputMode="decimal" required value={f.rate_per_qtl} onChange={set("rate_per_qtl")} />
        </Field>
        <Field label={t("gross")} hint={f.gross_amount === "" ? `= ${rupees(calcGross)}` : undefined}>
          <input className="input" type="number" step="0.01" min="0" inputMode="decimal" placeholder={calcGross.toFixed(0)} value={f.gross_amount} onChange={set("gross_amount")} />
        </Field>
        <Field label={t("net")} hint={f.net_amount === "" ? `= ${rupees(gross - dedTotal)}` : undefined}>
          <input className="input" type="number" step="0.01" min="0" inputMode="decimal" placeholder={(gross - dedTotal).toFixed(0)} value={f.net_amount} onChange={set("net_amount")} />
        </Field>
      </section>

      <section className="card space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="font-bold">{t("deductions")} <span className="text-sm font-normal text-stone-500">({rupees(dedTotal)})</span></h2>
          <button type="button" className="btn-ghost" onClick={() => setDeds([...deds, { label: "", kind: "other", amount: 0 }])}>+ {t("add_deduction")}</button>
        </div>
        {deds.map((d, i) => (
          <div key={i} className="grid grid-cols-[1fr_1fr_6rem_auto] gap-2">
            <input className="input" placeholder="हमाली / तोलाई" value={d.label}
              onChange={(e) => setDeds(deds.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
            <select className="input" value={d.kind} onChange={(e) => setDeds(deds.map((x, j) => (j === i ? { ...x, kind: e.target.value } : x)))}>
              {KINDS.map((k) => <option key={k} value={k}>{k.replace("_", " ")}</option>)}
            </select>
            <input className="input" type="number" min="0" step="0.01" value={d.amount}
              onChange={(e) => setDeds(deds.map((x, j) => (j === i ? { ...x, amount: Number(e.target.value) } : x)))} />
            <button type="button" className="px-2 text-red-600" aria-label="remove" onClick={() => setDeds(deds.filter((_, j) => j !== i))}>✕</button>
          </div>
        ))}
      </section>

      <section className="card grid gap-3 md:grid-cols-3">
        <Field label={t("payment_mode")}>
          <select className="input" value={f.payment_mode} onChange={set("payment_mode")}>
            {MODES.map((m) => <option key={m} value={m}>{t("mode_" + m)}</option>)}
          </select>
        </Field>
        <Field label={t("sale_date")}>
          <input className="input" type="date" required max={today()} value={f.sale_date} onChange={set("sale_date")} />
        </Field>
        <Field label={`${t("payment_due")} (${t("optional")})`}>
          <input className="input" type="date" value={f.payment_due} onChange={set("payment_due")} />
        </Field>
      </section>

      <ErrorNote error={error} />
      <button className="btn-primary w-full py-3 text-lg" disabled={busy}>{t("save_check")}</button>
    </form>
  );
}
