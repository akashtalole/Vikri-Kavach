import { useState, type FormEvent } from "react";
import { api, type Me } from "../api";
import { ErrorNote, Field } from "../components/ui";
import { useT } from "../i18n";
import { useSession } from "../session";

export default function Profile() {
  const { t, setLang } = useT();
  const { me, setMe } = useSession();
  const [f, setF] = useState({ name: me?.name ?? "", village: me?.village ?? "", district: me?.district ?? "", language: me?.language ?? "mr" });
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      setMe(await api.patch<Me>("/api/me", f));
      if (f.language === "mr" || f.language === "en") setLang(f.language);
      setMsg(t("saved"));
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <form onSubmit={save} className="card mx-auto max-w-lg space-y-3">
      <h1 className="text-xl font-bold">{t("profile")}</h1>
      <p className="text-sm text-stone-500">{me?.phone}</p>
      <Field label={t("name")}><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
      <Field label={t("village")}><input className="input" value={f.village} onChange={(e) => setF({ ...f, village: e.target.value })} /></Field>
      <Field label={t("district")}><input className="input" value={f.district} onChange={(e) => setF({ ...f, district: e.target.value })} /></Field>
      <Field label={t("language")}>
        <select className="input" value={f.language} onChange={(e) => setF({ ...f, language: e.target.value as Me["language"] })}>
          <option value="mr">मराठी</option>
          <option value="en">English</option>
        </select>
      </Field>
      <ErrorNote error={error} />
      {msg && <p className="text-sm text-emerald-700">{msg}</p>}
      <button className="btn-primary w-full">{t("save")}</button>
    </form>
  );
}
