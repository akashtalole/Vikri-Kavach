import { createContext, useContext } from "react";
import type { Me, Reference } from "./api";

export type Session = { me: Me | null; setMe: (m: Me | null) => void; ref: Reference | null };
export const SessionCtx = createContext<Session>({ me: null, setMe: () => {}, ref: null });
export const useSession = () => useContext(SessionCtx);
