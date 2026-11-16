"use client";

import { useAuth } from "@/lib/auth-context";

/**
 * Where the landing page's calls to action lead. Anonymous visitors are sent
 * into the real signup / login flow; signed-in users go straight to the app.
 * (While the session is still loading the visitor is treated as anonymous,
 * which matches the server-rendered HTML.)
 */
export function useLandingLinks() {
  const { user } = useAuth();
  return {
    signedIn: Boolean(user),
    primary: user ? { href: "/interviews/new", label: "Start an interview" } : { href: "/signup", label: "Start practising" },
    account: user ? { href: "/dashboard", label: "Dashboard" } : { href: "/login", label: "Log in" },
    history: user ? { href: "/history", label: "Review your history" } : { href: "/login", label: "Log in to review history" },
  };
}
