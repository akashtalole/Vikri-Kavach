import { useState, type FormEvent } from "react";
import { api, type Me } from "../api";
import { ErrorNote, Field } from "../components/ui";
import { useT } from "../i18n";
import { useSession } from "../session";

export default function Login() {
  const { t } = useT();
  const { setMe } = useSession();
  const [mode, setMode] = useState<"farmer" | "staff">("farmer");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [devCode, setDevCode] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<void>) => {
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
  const sendCode = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      const r = await api.post<{ dev_code: string | null }>("/api/auth/otp/request", { phone });
      setSent(true);
      setDevCode(r.dev_code);
    });
  };
  const verify = (e: FormEvent) => {
    e.preventDefault();
    run(async () => setMe(await api.post<Me>("/api/auth/otp/verify", { phone, code })));
  };
  const staffLogin = (e: FormEvent) => {
    e.preventDefault();
    run(async () => setMe(await api.post<Me>("/api/auth/staff/login", { username, password })));
  };

  return (
    <div className="mx-auto grid max-w-4xl gap-6 md:grid-cols-2 md:items-center">
      <section>
        <h1 className="text-3xl font-bold leading-tight text-brand-900">{t("tagline")}</h1>
        <ul className="mt-4 space-y-2 text-stone-700">
          {["⚖️ " + t("own_weight"), "📈 " + t("rate"), "🧾 " + t("deductions"), "💸 " + t("payments")].map((x) => (
            <li key={x} className="flex gap-2">{x}</li>
          ))}
        </ul>
        <p className="mt-4 rounded-xl bg-brand-50 p-3 text-sm text-brand-900 ring-1 ring-brand-100">
          <b>{t("why")}:</b> {t("why_text")}
        </p>
      </section>
      <section className="card">
        <div className="mb-4 grid grid-cols-2 gap-1 rounded-xl bg-stone-100 p-1">
          {(["farmer", "staff"] as const).map((m) => (
            <button key={m} onClick={() => { setMode(m); setError(null); }}
              className={`rounded-lg py-2 text-sm font-semibold ${mode === m ? "bg-white shadow-sm" : "text-stone-600"}`}>
              {t(m)}
            </button>
          ))}
        </div>
        {mode === "farmer" ? (
          !sent ? (
            <form onSubmit={sendCode} className="space-y-3">
              <Field label={t("phone")}>
                <input className="input" inputMode="numeric" autoComplete="tel" placeholder="98XXXXXXXX" required
                  value={phone} onChange={(e) => setPhone(e.target.value)} />
              </Field>
              <button className="btn-primary w-full" disabled={busy}>{t("send_code")}</button>
            </form>
          ) : (
            <form onSubmit={verify} className="space-y-3">
              {devCode && <p className="rounded-xl bg-amber-50 p-3 text-sm ring-1 ring-amber-200">{t("dev_code")} <b className="font-mono text-lg">{devCode}</b></p>}
              <Field label={t("code")}>
                <input className="input font-mono tracking-widest" inputMode="numeric" autoComplete="one-time-code" maxLength={6} required
                  value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
              </Field>
              <button className="btn-primary w-full" disabled={busy || code.length !== 6}>{t("verify")}</button>
              <button type="button" className="w-full text-sm text-stone-500 underline" onClick={() => { setSent(false); setCode(""); }}>
                {t("back")}
              </button>
            </form>
          )
        ) : (
          <form onSubmit={staffLogin} className="space-y-3">
            <Field label={t("username")}>
              <input className="input" autoComplete="username" required value={username} onChange={(e) => setUsername(e.target.value)} />
            </Field>
            <Field label={t("password")}>
              <input className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <button className="btn-primary w-full" disabled={busy}>{t("login")}</button>
          </form>
        )}
        <div className="mt-3"><ErrorNote error={error} /></div>
      </section>
    </div>
  );
}
