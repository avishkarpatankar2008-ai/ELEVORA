"use client";

import { useEffect, useState } from "react";
import { Badge, type BadgeTone } from "@/components/Badge";
import type { PostureSnapshot, PostureStatus } from "@/lib/posture";
import type { TrackerStatus, WebcamAnalyticsTracker } from "@/lib/webcamAnalytics";

const STATUS_LABEL: Record<PostureStatus, string> = {
  good: "Good",
  needs_correction: "Needs correction",
  calibrating: "Calibrating",
  no_tracking: "Can't see you",
};

const STATUS_TONE: Record<PostureStatus, BadgeTone> = {
  good: "success",
  needs_correction: "warning",
  calibrating: "blue",
  no_tracking: "neutral",
};

function snapshotKey(s: PostureSnapshot) {
  return [
    s.status,
    s.message,
    s.lighting,
    s.calibrated,
    s.consistency === null ? "-" : Math.round(s.consistency * 100),
  ].join("|");
}

/**
 * Live Good / Needs correction status and the current corrective message.
 *
 * Subscribes to the tracker directly and re-renders only when what is shown
 * changes, so ~5 pose updates a second don't re-render the whole interview room.
 * Posture feedback is practice guidance and is deliberately separate from the
 * interview score.
 */
export function PosturePanel({
  tracker,
  analyticsStatus,
}: {
  tracker: WebcamAnalyticsTracker | null;
  analyticsStatus: TrackerStatus;
}) {
  const [snapshot, setSnapshot] = useState<PostureSnapshot | null>(null);

  useEffect(() => {
    if (!tracker) return;
    setSnapshot(null);
    let shownKey = "";
    return tracker.subscribe((frame) => {
      const key = snapshotKey(frame.snapshot);
      if (key === shownKey) return;
      shownKey = key;
      setSnapshot(frame.snapshot);
    });
  }, [tracker]);

  if (analyticsStatus === "failed") {
    return (
      <div className="border-t border-line px-4 py-3 text-[11px] leading-5 text-ink-mute" role="status">
        Live posture feedback couldn&apos;t start in this browser (the on-device model didn&apos;t
        load). The interview and your other scores are unaffected.
      </div>
    );
  }

  const status: PostureStatus = snapshot?.status ?? "calibrating";
  const message = snapshot?.message ?? (snapshot ? null : "Starting on-device posture tracking…");

  return (
    <div className="border-t border-line px-4 py-3" data-testid="posture-panel">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-mute">
          Posture
        </span>
        <Badge tone={STATUS_TONE[status]}>{snapshot ? STATUS_LABEL[status] : "Starting"}</Badge>
      </div>

      <p
        role="status"
        aria-live="polite"
        className={`mt-2 min-h-[2.5rem] text-sm leading-5 ${
          status === "needs_correction" ? "text-warning" : "text-ink-soft"
        }`}
      >
        {status === "good" && !message ? "Looking good — keep it up." : message}
      </p>

      {snapshot?.lighting === "dim" && (
        <p className="mt-1 text-[11px] leading-5 text-ink-mute">
          Lighting looks dim — tracking may be less reliable. Face a window or lamp if you can.
        </p>
      )}

      <div className="mt-2 flex items-center justify-between gap-3 text-[11px] text-ink-mute">
        <span>
          {snapshot?.consistency != null
            ? `Consistency so far: ${Math.round(snapshot.consistency * 100)}%`
            : "Consistency appears after a few seconds"}
        </span>
        <button
          type="button"
          onClick={() => tracker?.recalibratePosture()}
          className="rounded-lg border border-line px-2 py-1 font-medium text-ink-soft transition-colors hover:border-line-strong hover:text-ink"
        >
          Recalibrate
        </button>
      </div>
      <p className="mt-2 text-[11px] leading-5 text-ink-mute">
        Rough estimates from your own upright position. Sit tall, then press Recalibrate if the
        first reading looks off. Not part of your interview score.
      </p>
    </div>
  );
}
