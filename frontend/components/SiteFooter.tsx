"use client";

import { usePathname } from "next/navigation";

/** App footer. The landing page ("/") renders its own footer, so this stays out of its way. */
export function SiteFooter() {
  const pathname = usePathname();
  if (pathname === "/") return null;
  return (
    <footer className="mt-16 border-t border-line bg-white">
      <div className="mx-auto flex max-w-7xl flex-col justify-between gap-3 px-4 py-8 text-xs text-ink-mute sm:flex-row sm:items-center sm:px-6 lg:px-8">
        <div className="flex flex-col gap-1">
          <span className="font-semibold tracking-wide text-ink-soft">ELEVORA</span>
          <span>Practice the interview, not a script.</span>
        </div>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <span>© {new Date().getFullYear()} ELEVORA</span>
          <span className="hidden text-ink-mute/60 sm:inline" aria-hidden="true">
            ·
          </span>
          <span>Camera frames never leave your browser.</span>
        </div>
      </div>
    </footer>
  );
}
