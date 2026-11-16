"use client";

import { FormEvent, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Alert } from "@/components/Alert";
import { Button } from "@/components/Button";

function ProfileContent() {
  const { user, updateProfile } = useAuth();
  const [name, setName] = useState(user?.name ?? "");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => setName(user?.name ?? ""), [user?.name]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true); setMessage(""); setError("");
    try {
      await updateProfile({ name: name.trim() });
      setMessage("Profile updated.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Profile could not be updated.");
    } finally { setSaving(false); }
  }

  return <div className="mx-auto w-full max-w-5xl px-4 py-10 sm:px-6 lg:px-8 lg:py-16">
    <p className="eyebrow">Account details</p>
    <h1 className="mt-3 text-display-title text-5xl sm:text-6xl">Your profile<span className="onda-dot" /></h1>
    <p className="mt-4 max-w-xl text-base text-ink-soft">Manage the identity attached to your ELEVORA practice sessions.</p>
    <div className="mt-10 grid gap-6 lg:grid-cols-[240px_minmax(0,1fr)]">
      <aside className="rounded-2xl bg-surface-2 p-6">
        <div className="grid h-16 w-16 place-items-center rounded-full bg-violet text-xl font-bold text-white">{(user?.name || user?.email || "E").split(/\s+/).map(p => p[0]).slice(0,2).join("").toUpperCase()}</div>
        <p className="mt-4 break-words font-semibold">{user?.name || "ELEVORA member"}</p>
        <p className="mt-1 break-all text-sm text-ink-mute">{user?.email}</p>
        <div className="mt-6 border-t border-line pt-4"><p className="text-xs uppercase tracking-wider text-ink-mute">Member since</p><p className="mt-1 text-sm font-medium">{user?.createdAt ? new Date(user.createdAt).toLocaleDateString(undefined,{year:"numeric",month:"long",day:"numeric"}) : "Unavailable"}</p></div>
      </aside>
      <section className="rounded-2xl border border-line bg-white p-6 sm:p-8">
        <h2 className="font-display text-2xl font-bold">Personal information</h2>
        <p className="mt-2 text-sm text-ink-soft">These details come from your authenticated account. Email changes are not exposed by the current API.</p>
        {message && <div className="mt-5"><Alert tone="success">{message}</Alert></div>}
        {error && <div className="mt-5"><Alert tone="error">{error}</Alert></div>}
        <form onSubmit={submit} className="mt-6 space-y-5">
          <label className="block"><span className="mb-2 block text-sm font-semibold">Full name</span><input required maxLength={120} value={name} onChange={e => setName(e.target.value)} className="w-full rounded-xl border border-line-strong bg-white px-4 py-3 text-sm outline-none focus:border-violet" /></label>
          <label className="block"><span className="mb-2 block text-sm font-semibold">Email address</span><input value={user?.email ?? ""} readOnly className="w-full cursor-not-allowed rounded-xl border border-line bg-surface-2 px-4 py-3 text-sm text-ink-mute" /></label>
          <div className="pt-2"><Button type="submit" disabled={saving || !name.trim() || name.trim() === user?.name}>{saving ? "Saving…" : "Save changes"}</Button></div>
        </form>
      </section>
    </div>
  </div>;
}

export default function ProfilePage() {
  return <ProtectedRoute><ProfileContent /></ProtectedRoute>;
}
