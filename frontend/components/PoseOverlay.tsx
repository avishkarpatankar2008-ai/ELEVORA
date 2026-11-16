"use client";

import { useEffect, useRef } from "react";
import {
  mapPointToCoverBox,
  POSE_OVERLAY_CONNECTIONS,
  POSE_OVERLAY_POINTS,
  type PostureStatus,
} from "@/lib/posture";
import type { LivePoseFrame, WebcamAnalyticsTracker } from "@/lib/webcamAnalytics";

const MIN_VISIBILITY = 0.5;

const STATUS_COLOUR: Record<PostureStatus, string> = {
  good: "rgb(74, 222, 128)",
  needs_correction: "rgb(251, 191, 36)",
  calibrating: "rgb(131, 166, 206)",
  no_tracking: "rgb(147, 163, 184)",
};

/**
 * Skeleton drawn over the self-view from the landmarks the tracker already
 * computed. Purely visual and local: the canvas is never read back, and no
 * landmark leaves this tab. Sits over a `object-cover` video, so points are
 * mapped through the same crop the video undergoes.
 */
export function PoseOverlay({ tracker }: { tracker: WebcamAnalyticsTracker | null }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (!tracker) return;
    const canvas = canvasRef.current;
    if (!canvas) return;

    const draw = (frame: LivePoseFrame) => {
      const context = canvas.getContext("2d");
      if (!context) return;
      const ratio = window.devicePixelRatio || 1;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
        canvas.width = Math.round(width * ratio);
        canvas.height = Math.round(height * ratio);
      }
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);

      const landmarks = frame.landmarks;
      if (!landmarks || frame.snapshot.status === "no_tracking") return;

      const video = { width: frame.videoWidth, height: frame.videoHeight };
      const box = { width, height };
      const visible = (index: number) => (landmarks[index]?.visibility ?? 0) >= MIN_VISIBILITY;
      const place = (index: number) => mapPointToCoverBox(landmarks[index], video, box);
      const colour = STATUS_COLOUR[frame.snapshot.status];

      context.lineWidth = 2;
      context.lineCap = "round";
      context.strokeStyle = colour;
      context.globalAlpha = 0.9;
      for (const [from, to] of POSE_OVERLAY_CONNECTIONS) {
        if (!landmarks[from] || !landmarks[to] || !visible(from) || !visible(to)) continue;
        const a = place(from);
        const b = place(to);
        context.beginPath();
        context.moveTo(a.x, a.y);
        context.lineTo(b.x, b.y);
        context.stroke();
      }
      context.fillStyle = colour;
      for (const index of POSE_OVERLAY_POINTS) {
        if (!landmarks[index] || !visible(index)) continue;
        const p = place(index);
        context.beginPath();
        context.arc(p.x, p.y, 3, 0, Math.PI * 2);
        context.fill();
      }
      context.globalAlpha = 1;
    };

    const unsubscribe = tracker.subscribe(draw);
    return () => {
      unsubscribe();
      canvas.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
    };
  }, [tracker]);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 h-full w-full"
    />
  );
}
