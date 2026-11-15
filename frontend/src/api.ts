export type Severity = "high" | "medium" | "info" | "ok";
export type Finding = { severity: Severity; code: string; message: string; data?: Record<string, number> };
export type Deduction = { label: string; kind: string; amount: number };
export type Me = {
  id: number; role: "farmer" | "officer" | "admin"; name: string | null; phone: string | null; username: string | null;
  language: "mr" | "hi" | "en"; village: string | null; district: string | null; apmc_code: string | null; apmc_name: string | null;
};
export type Sale = {
  id: number; reference: string; apmc_code: string; apmc_name: string; market_name: string; trader_name: string;
  trader_registered: boolean; trader_status: string | null; licence_no: string; commodity_code: string; crop: string;
  variety: string; bags: number | null; own_weight_qtl: number | null; slip_weight_qtl: number; rate_per_qtl: number;
  gross_amount: number; deductions: Deduction[]; net_amount: number; payment_mode: string; sale_date: string;
  payment_due: string; amount_paid: number; outstanding: number; status: string;
  evidence: { id: number; kind: string; content_type: string; uploaded_at: string }[];
  payments: { kind: string; amount: number; on_date: string; note: string }[];
  findings: Finding[]; risk: "high" | "medium" | "low";
  complaint?: { id: number; reference: string; status: string; officer_note: string } | null;
};
export type Reference = {
  crops: { code: string; en: string; mr: string }[];
  apmcs: { code: string; name_en: string; name_mr: string; district: string }[];
  price_markets: string[];
  complaint_categories: string[];
  ai_slip_reading: boolean;
};
export type TraderRow = {
  licence_no: string; name: string; registered: boolean; status: string | null; sales: number; overdue_count: number;
  overdue_amount: number; bounced: number; weight_gap_sales: number; low_rate_sales: number; complaints: number; flag: boolean;
};
export type ComplaintRow = {
  id: number; reference: string; status: string; categories: string[]; sale_id: number; sale_reference: string;
  created_at: string; officer_note: string;
};
export type Notice = { id: number; text: string; link: string; read: boolean; at: string };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: { "x-requested-with": "vikrikavach" } };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["content-type"] = "application/json";
  }
  const res = await fetch(path, init);
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : Array.isArray(j.detail) ? j.detail.map((d: { msg: string }) => d.msg).join("; ") : msg;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, b?: unknown) => request<T>("POST", p, b ?? {}),
  patch: <T>(p: string, b: unknown) => request<T>("PATCH", p, b),
};

export const rupees = (n: number) => "₹" + Math.round(n).toLocaleString("en-IN");
export const today = () => new Date(Date.now() + 5.5 * 3600_000).toISOString().slice(0, 10);
