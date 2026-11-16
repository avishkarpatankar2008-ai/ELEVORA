"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { interviewsApi } from "@/lib/api";
import type { Interview } from "@/lib/types";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { ButtonLink } from "@/components/Button";
import { EmptyState } from "@/components/EmptyState";

const PAGE_SIZE = 20;

function label(status: Interview["status"]) {
  return ({ completed: "Completed", in_progress: "In progress", draft: "Not started", abandoned: "Ended early" } as const)[status] ?? status;
}

function HistoryContent() {
  const [items, setItems] = useState<Interview[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasNext, setHasNext] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("newest");
  const [query, setQuery] = useState("");

  const load = useCallback(async (nextOffset: number) => {
    setLoading(true);
    setError("");
    try {
      const page = await interviewsApi.list({ limit: PAGE_SIZE, offset: nextOffset });
      setItems(page);
      setOffset(nextOffset);
      setHasNext(page.length === PAGE_SIZE);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Interview history could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(0); }, [load]);

  const visible = items.filter((item) => {
    const matchesStatus = filter === "all" || item.status === filter;
    const haystack = [item.role, item.company, item.exam, item.category].filter(Boolean).join(" ").toLowerCase();
    return matchesStatus && haystack.includes(query.trim().toLowerCase());
  }).sort((a, b) => sort === "oldest"
    ? new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
    : new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());

  return <div className="mx-auto w-full max-w-7xl px-4 py-10 sm:px-6 lg:px-8 lg:py-16">
    <div className="flex flex-col justify-between gap-6 border-b border-line pb-8 sm:flex-row sm:items-end">
      <div>
        <p className="eyebrow">Your practice, documented</p>
        <h1 className="mt-3 text-display-title text-5xl sm:text-6xl">Interview history<span className="onda-dot" /></h1>
        <p className="mt-4 max-w-xl text-base text-ink-soft">Return to a saved session, continue unfinished practice, or review a completed report.</p>
      </div>
      <ButtonLink href="/interviews/new">Start an interview <span aria-hidden="true">↗</span></ButtonLink>
    </div>

    <div className="mt-8 grid gap-3 md:grid-cols-[minmax(0,1fr)_190px_190px]">
      <label className="block"><span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-ink-mute">Search this page</span>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Role, company, exam…" className="w-full rounded-xl border border-line-strong bg-white px-4 py-3 text-sm outline-none transition focus:border-violet" /></label>
      <label className="block"><span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-ink-mute">Status</span>
        <select value={filter} onChange={(e) => setFilter(e.target.value)} className="w-full rounded-xl border border-line-strong bg-white px-4 py-3 text-sm">
          <option value="all">All statuses</option><option value="completed">Completed</option><option value="in_progress">In progress</option><option value="draft">Not started</option><option value="abandoned">Ended early</option>
        </select></label>
      <label className="block"><span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-ink-mute">Sort</span>
        <select value={sort} onChange={(e) => setSort(e.target.value)} className="w-full rounded-xl border border-line-strong bg-white px-4 py-3 text-sm">
          <option value="newest">Newest first</option><option value="oldest">Oldest first</option>
        </select></label>
    </div>

    {error && <div role="alert" className="mt-6 rounded-2xl border border-danger/30 bg-danger/5 p-5"><p className="font-semibold">Couldn’t load history</p><p className="mt-1 text-sm text-ink-soft">{error}</p><button className="mt-3 font-semibold text-violet underline underline-offset-4" onClick={() => void load(offset)}>Try again</button></div>}
    <div className="mt-6 overflow-hidden rounded-2xl border border-line bg-white">
      {loading ? <div className="space-y-3 p-6" role="status" aria-label="Loading interview history">{[1,2,3,4].map(n => <div key={n} className="h-16 animate-pulse rounded-xl bg-surface-2" />)}</div>
      : visible.length === 0 ? <div className="p-8"><EmptyState title={items.length ? "No matches on this page" : "Your first session starts here"} description={items.length ? "Try another search or status filter. Search and filters apply to the currently loaded page." : "Complete an interview and your saved sessions will appear here."} action={!items.length ? <ButtonLink href="/interviews/new">Create an interview</ButtonLink> : undefined} /></div>
      : <div className="divide-y divide-line">{visible.map((item) => <article key={item.id} className="group flex flex-col gap-4 p-5 transition hover:bg-surface-2/60 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2"><span className="rounded-full bg-violet/10 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide text-violet">{label(item.status)}</span><span className="text-xs text-ink-mute">{new Date(item.createdAt).toLocaleDateString(undefined,{year:"numeric",month:"short",day:"numeric"})}</span></div>
          <h2 className="mt-2 truncate font-display text-xl font-bold tracking-tight">{item.role || item.exam || item.category}</h2>
          <p className="mt-1 text-sm text-ink-soft">{[item.company, item.experienceLevel, item.difficulty ? `${item.difficulty} difficulty` : ""].filter(Boolean).join(" · ") || "Interview practice"}</p>
        </div>
        <div className="flex shrink-0 gap-2">
          {item.status === "completed" ? <Link href={`/results/${encodeURIComponent(item.id)}`} className="rounded-full border border-line-strong px-4 py-2 text-sm font-semibold transition hover:border-violet hover:text-violet">View report ↗</Link> : <Link href={`/interviews/${encodeURIComponent(item.id)}`} className="rounded-full bg-violet px-4 py-2 text-sm font-semibold text-white transition hover:bg-violet-deep">{item.status === "in_progress" ? "Resume" : "Open interview"} ↗</Link>}
        </div>
      </article>)}</div>}
    </div>

    <div className="mt-5 flex items-center justify-between gap-4">
      <p className="text-xs text-ink-mute">Page {Math.floor(offset / PAGE_SIZE) + 1} · {items.length} records loaded{hasNext ? " · more available" : ""}</p>
      <div className="flex gap-2"><button disabled={offset === 0 || loading} onClick={() => void load(Math.max(0, offset - PAGE_SIZE))} className="rounded-full border border-line-strong px-4 py-2 text-sm font-semibold disabled:opacity-40">Previous</button><button disabled={!hasNext || loading} onClick={() => void load(offset + PAGE_SIZE)} className="rounded-full border border-line-strong px-4 py-2 text-sm font-semibold disabled:opacity-40">Next</button></div>
    </div>
  </div>;
}

export default function HistoryPage() {
  return <ProtectedRoute><HistoryContent /></ProtectedRoute>;
}
