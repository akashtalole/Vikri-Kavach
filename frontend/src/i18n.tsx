import { createContext, useContext, useState, type ReactNode } from "react";

export type Lang = "mr" | "en";

const mr: Record<string, string> = {
  tagline: "प्रत्येक विक्रीची तपासणी: वजन, भाव, कपात आणि पेमेंट",
  farmer: "शेतकरी", staff: "बाजार समिती अधिकारी", phone: "मोबाईल नंबर", send_code: "कोड पाठवा", code: "OTP कोड",
  verify: "लॉगिन करा", username: "युजरनेम", password: "पासवर्ड", login: "लॉगिन", logout: "बाहेर पडा",
  dev_code: "चाचणी मोड: तुमचा कोड", my_sales: "माझ्या विक्री", new_sale: "नवीन विक्री नोंदवा", profile: "प्रोफाइल",
  notifications: "सूचना", no_sales: "अजून कोणतीही विक्री नोंदवलेली नाही. पट्टी मिळाल्यावर लगेच नोंद करा.",
  outstanding: "बाकी रक्कम", overdue_total: "थकीत पेमेंट", sales_count: "विक्री", high_risk: "धोक्याच्या विक्री",
  read_slip: "पट्टीचा फोटो वाचा (AI)", reading: "वाचत आहे…", slip_read_ok: "पट्टी वाचली. आकडे तपासा आणि सेव्ह करा.",
  apmc: "बाजार समिती", market: "भाव तुलनेसाठी बाजार", trader_licence: "व्यापारी परवाना क्रमांक", trader_name: "व्यापाऱ्याचे नाव",
  crop: "पीक", variety: "जात", bags: "पोती", own_weight: "तुमच्या वजनकाट्याचे वजन (क्विंटल)", slip_weight: "पट्टीवरील वजन (क्विंटल)",
  rate: "भाव (₹/क्विंटल)", gross: "एकूण रक्कम", deductions: "कपात", add_deduction: "कपात जोडा", net: "निव्वळ देय रक्कम",
  payment_mode: "पेमेंट पद्धत", sale_date: "विक्री दिनांक", payment_due: "पेमेंट देय दिनांक", save_check: "सेव्ह करा आणि तपासा",
  checks: "तपासणी", evidence: "पुरावे", add_photo: "फोटो जोडा", payments: "पेमेंट नोंदी", record_payment: "पेमेंट नोंदवा",
  received: "मिळाले", cheque_bounced: "चेक बाउन्स", promised: "आश्वासन", amount: "रक्कम", date: "दिनांक", note: "टीप",
  complaint: "तक्रार", raise_complaint: "बाजार समितीकडे तक्रार करा", describe: "काय घडले ते लिहा", submit: "पाठवा",
  pack: "पुरावा पॅक उघडा / प्रिंट करा", risk_high: "धोका जास्त", risk_medium: "लक्ष द्या", risk_low: "ठीक दिसते",
  registered: "परवाना नोंदणीत आहे", not_registered: "परवाना नोंदणीत नाही", save: "सेव्ह", name: "नाव", village: "गाव",
  district: "जिल्हा", language: "भाषा", dashboard: "डॅशबोर्ड", traders: "व्यापारी", complaints: "तक्रारी",
  back: "मागे", search_apmc: "बाजार समिती शोधा", optional: "ऐच्छिक", lookup: "तपासा", saved: "सेव्ह झाले",
  status_awaiting_payment: "पेमेंटची वाट", status_partly_paid: "अर्धवट पेमेंट", status_paid: "पूर्ण पेमेंट",
  status_overdue: "थकीत", status_bounced: "चेक बाउन्स", status_disputed: "तक्रार केली",
  cat_weight: "वजनात फसवणूक", cat_rate: "कमी भाव", cat_deductions: "जास्त कपात", cat_payment_delay: "पेमेंट उशीर",
  cat_cheque_bounced: "चेक बाउन्स", cat_unlicensed_trader: "विनापरवाना व्यापारी", cat_quality_downgrade: "दर्जा कमी दाखवला",
  cat_other: "इतर", kind_patti: "पट्टी", kind_weighbridge: "वजनकाटा पावती", kind_cheque: "चेक", kind_produce: "माल", kind_other: "इतर",
  mode_cash: "रोख", mode_cheque: "चेक", mode_bank_transfer: "बँक ट्रान्सफर", mode_upi: "UPI", mode_not_stated: "नमूद नाही",
  why: "हे का महत्त्वाचे?", why_text: "स्वतःचे वजन, पट्टी आणि पेमेंटची नोंद असेल तर फसवणूक सिद्ध करणे सोपे होते.",
};

const en: Record<string, string> = {
  tagline: "Check every sale for weight, rate, deduction and payment fraud",
  farmer: "Farmer", staff: "APMC staff", phone: "Mobile number", send_code: "Send code", code: "OTP code", verify: "Log in",
  username: "Username", password: "Password", login: "Log in", logout: "Log out", dev_code: "Test mode: your code is",
  my_sales: "My sales", new_sale: "Record a sale", profile: "Profile", notifications: "Notifications",
  no_sales: "No sales yet. Record each sale as soon as you get the slip.", outstanding: "Outstanding",
  overdue_total: "Overdue", sales_count: "Sales", high_risk: "High-risk sales", read_slip: "Read slip photo (AI)",
  reading: "Reading…", slip_read_ok: "Slip read. Check the numbers, then save.", apmc: "APMC",
  market: "Market for price comparison", trader_licence: "Trader licence no.", trader_name: "Trader name", crop: "Crop",
  variety: "Variety", bags: "Bags", own_weight: "Your weighbridge weight (qtl)", slip_weight: "Weight on slip (qtl)",
  rate: "Rate (₹/qtl)", gross: "Gross amount", deductions: "Deductions", add_deduction: "Add deduction", net: "Net payable",
  payment_mode: "Payment mode", sale_date: "Sale date", payment_due: "Payment due", save_check: "Save and check",
  checks: "Checks", evidence: "Evidence", add_photo: "Add photo", payments: "Payments", record_payment: "Record payment",
  received: "Received", cheque_bounced: "Cheque bounced", promised: "Promised", amount: "Amount", date: "Date", note: "Note",
  complaint: "Complaint", raise_complaint: "Complain to the APMC", describe: "Describe what happened", submit: "Submit",
  pack: "Open / print evidence pack", risk_high: "High risk", risk_medium: "Needs attention", risk_low: "Looks fine",
  registered: "Licence in register", not_registered: "Licence not in register", save: "Save", name: "Name",
  village: "Village", district: "District", language: "Language", dashboard: "Dashboard", traders: "Traders",
  complaints: "Complaints", back: "Back", search_apmc: "Search APMC", optional: "optional", lookup: "Check",
  saved: "Saved", status_awaiting_payment: "Awaiting payment", status_partly_paid: "Partly paid", status_paid: "Paid",
  status_overdue: "Overdue", status_bounced: "Cheque bounced", status_disputed: "Disputed",
  cat_weight: "Weight cheating", cat_rate: "Low rate", cat_deductions: "Excess deductions", cat_payment_delay: "Payment delay",
  cat_cheque_bounced: "Cheque bounced", cat_unlicensed_trader: "Unlicensed trader", cat_quality_downgrade: "Quality downgraded",
  cat_other: "Other", kind_patti: "Slip (patti)", kind_weighbridge: "Weighbridge receipt", kind_cheque: "Cheque",
  kind_produce: "Produce", kind_other: "Other", mode_cash: "Cash", mode_cheque: "Cheque", mode_bank_transfer: "Bank transfer",
  mode_upi: "UPI", mode_not_stated: "Not stated", why: "Why this matters",
  why_text: "With your own weight, the slip and payment records, cheating is easy to prove.",
};

const LangCtx = createContext<{ lang: Lang; setLang: (l: Lang) => void; t: (k: string) => string }>({
  lang: "mr", setLang: () => {}, t: (k) => k,
});

function initial(): Lang {
  try {
    const v = localStorage.getItem("vk_lang");
    if (v === "en" || v === "mr") return v;
  } catch {
    /* storage blocked */
  }
  return "mr";
}

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initial);
  const setLang = (l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem("vk_lang", l);
    } catch {
      /* ignore */
    }
    document.documentElement.lang = l;
  };
  const dict = lang === "mr" ? mr : en;
  return <LangCtx.Provider value={{ lang, setLang, t: (k) => dict[k] ?? en[k] ?? k }}>{children}</LangCtx.Provider>;
}

export const useT = () => useContext(LangCtx);
