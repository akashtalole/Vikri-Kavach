import { StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, NavLink, Navigate, Route, Routes, useNavigate } from "react-router";
import { api, type Me, type Notice, type Reference } from "./api";
import { LangProvider, useT } from "./i18n";
import "./index.css";
import Login from "./pages/Login";
import NewSale from "./pages/NewSale";
import OfficerComplaint from "./pages/OfficerComplaint";
import OfficerDashboard from "./pages/OfficerDashboard";
import OfficerTraders from "./pages/OfficerTraders";
import Profile from "./pages/Profile";
import SaleDetail from "./pages/SaleDetail";
import Sales from "./pages/Sales";
import { SessionCtx, useSession } from "./session";


function Shield() {
  return (
    <svg viewBox="0 0 64 64" className="size-8" aria-hidden>
      <path d="M32 4 8 13v17c0 15 10 26 24 30 14-4 24-15 24-30V13Z" fill="#fff" opacity=".95" />
      <path d="m21 33 8 8 15-17" fill="none" stroke="#15803d" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Bell() {
  const [items, setItems] = useState<Notice[]>([]);
  const [open, setOpen] = useState(false);
  const { t } = useT();
  const nav = useNavigate();
  useEffect(() => {
    api.get<Notice[]>("/api/notifications").then(setItems).catch(() => {});
  }, []);
  const unread = items.filter((n) => !n.read).length;
  const toggle = () => {
    setOpen(!open);
    if (!open && unread) api.post("/api/notifications/read").then(() => setItems(items.map((n) => ({ ...n, read: true }))));
  };
  return (
    <div className="relative">
      <button onClick={toggle} className="relative rounded-full p-2 hover:bg-white/10" aria-label={t("notifications")}>
        <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 grid size-5 place-items-center rounded-full bg-amber-400 text-xs font-bold text-amber-950">
            {unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-2xl bg-white p-2 text-stone-900 shadow-xl ring-1 ring-stone-200">
          <div className="px-2 py-1 text-sm font-bold">{t("notifications")}</div>
          {items.length === 0 && <p className="p-2 text-sm text-stone-500">—</p>}
          <ul className="max-h-96 overflow-auto">
            {items.map((n) => (
              <li key={n.id}>
                <button className="w-full rounded-xl p-2 text-left text-sm hover:bg-stone-100" onClick={() => { setOpen(false); nav(n.link); }}>
                  {n.text}
                  <span className="block text-xs text-stone-500">{new Date(n.at).toLocaleString()}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const { me, setMe } = useSession();
  const { t, lang, setLang } = useT();
  const nav = useNavigate();
  const logout = async () => {
    await api.post("/api/auth/logout");
    setMe(null);
    nav("/login");
  };
  const link = ({ isActive }: { isActive: boolean }) =>
    `rounded-lg px-3 py-1.5 text-sm font-semibold ${isActive ? "bg-white text-brand-800" : "text-white/90 hover:bg-white/10"}`;
  return (
    <div className="min-h-dvh">
      <header className="bg-brand-800 text-white">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-3">
          <Link to="/" className="flex items-center gap-2">
            <Shield />
            <span className="text-lg font-bold">{lang === "mr" ? "विक्री कवच" : "Vikri Kavach"}</span>
          </Link>
          <div className="ml-auto flex items-center gap-1">
            <button className="rounded-lg px-2 py-1 text-sm font-semibold ring-1 ring-white/30" onClick={() => setLang(lang === "mr" ? "en" : "mr")}>
              {lang === "mr" ? "EN" : "मराठी"}
            </button>
            {me && <Bell />}
          </div>
        </div>
        {me && (
          <nav className="mx-auto flex max-w-5xl flex-wrap gap-1 px-4 pb-2">
            {me.role === "farmer" ? (
              <>
                <NavLink to="/" end className={link}>{t("my_sales")}</NavLink>
                <NavLink to="/sales/new" className={link}>{t("new_sale")}</NavLink>
                <NavLink to="/profile" className={link}>{t("profile")}</NavLink>
              </>
            ) : (
              <>
                <NavLink to="/officer" end className={link}>{t("dashboard")}</NavLink>
                <NavLink to="/officer/traders" className={link}>{t("traders")}</NavLink>
              </>
            )}
            <button onClick={logout} className="ml-auto rounded-lg px-3 py-1.5 text-sm text-white/80 hover:bg-white/10">{t("logout")}</button>
          </nav>
        )}
      </header>
      <main className="mx-auto max-w-5xl px-4 py-5">{children}</main>
    </div>
  );
}

function App() {
  const [me, setMeState] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);
  const [ref, setRef] = useState<Reference | null>(null);
  const setMe = useCallback((m: Me | null) => setMeState(m), []);
  useEffect(() => {
    api.get<Me>("/api/me").then(setMeState).catch(() => setMeState(null)).finally(() => setReady(true));
    api.get<Reference>("/api/reference").then(setRef).catch(() => {});
  }, []);
  if (!ready) return <div className="grid min-h-dvh place-items-center text-stone-500">…</div>;
  const home = !me ? "/login" : me.role === "farmer" ? "/" : "/officer";
  const farmer = me?.role === "farmer";
  const staff = me && me.role !== "farmer";
  return (
    <SessionCtx.Provider value={{ me, setMe, ref }}>
      <Shell>
        <Routes>
          <Route path="/login" element={me ? <Navigate to={home} replace /> : <Login />} />
          <Route path="/" element={farmer ? <Sales /> : <Navigate to={home} replace />} />
          <Route path="/sales/new" element={farmer ? <NewSale /> : <Navigate to={home} replace />} />
          <Route path="/sales/:id" element={me ? <SaleDetail /> : <Navigate to="/login" replace />} />
          <Route path="/profile" element={farmer ? <Profile /> : <Navigate to={home} replace />} />
          <Route path="/officer" element={staff ? <OfficerDashboard /> : <Navigate to={home} replace />} />
          <Route path="/officer/traders" element={staff ? <OfficerTraders /> : <Navigate to={home} replace />} />
          <Route path="/officer/complaints/:id" element={staff ? <OfficerComplaint /> : <Navigate to={home} replace />} />
          <Route path="*" element={<Navigate to={home} replace />} />
        </Routes>
      </Shell>
    </SessionCtx.Provider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <LangProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </LangProvider>
  </StrictMode>,
);
