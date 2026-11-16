/**
 * Live posture feedback, computed entirely in the browser from the pose
 * landmarks the existing MediaPipe Pose Landmarker already produces.
 *
 * Privacy: this module is pure maths over a handful of numbers. It has no DOM,
 * network, storage or camera access, and it never retains frames or landmark
 * history beyond a few seconds of smoothed positions used for the movement
 * estimate. Nothing here is uploaded; the only thing the rest of the app may
 * keep is the aggregate {@link PostureSessionSummary}, shown to the candidate.
 *
 * Scope: these are coarse, camera-visible geometric estimates from a single
 * webcam. They are not medical or ergonomic advice and say nothing about
 * honesty, emotion, intelligence, personality or job suitability. They are kept
 * entirely separate from interview performance scores.
 *
 * Design for a desk webcam: only the head and shoulders are assumed visible
 * (hips almost never are), so every measurement uses nose, ears and shoulders.
 * Measurements are divided by shoulder width so they don't depend on how far
 * the candidate sits from the camera, and "slouch / forward head" are judged
 * against the candidate's *own* upright baseline captured in the first few
 * seconds (they can recalibrate at any time) — a fixed pixel threshold would be
 * wrong for most bodies and cameras.
 *
 * Stability: every issue has separate enter/exit thresholds (hysteresis), must
 * persist for a minimum time before it is shown and for a minimum time before
 * it clears (debounce), measurements are exponentially smoothed, and a message
 * stays on screen for a minimum time — so feedback doesn't flicker.
 * Thresholds are sensible defaults, not calibrated against real recordings.
 */

export type PostureIssueId =
  | "framing"
  | "slouch"
  | "forward_head"
  | "head_tilt"
  | "uneven_shoulders"
  | "movement";

export type PostureStatus = "calibrating" | "good" | "needs_correction" | "no_tracking";
export type LightingState = "ok" | "dim" | "unknown";
export type FramingProblem = "shoulders_cut" | "head_cut" | "too_close" | "too_far" | "off_center";
export type PostureRating = "consistent" | "mostly_consistent" | "needs_attention";

export interface PoseLandmark {
  x: number;
  y: number;
  z?: number;
  visibility?: number;
  presence?: number;
}

type Point = { x: number; y: number };

// MediaPipe Pose indices.
const NOSE = 0;
const LEFT_EAR = 7;
const RIGHT_EAR = 8;
const LEFT_SHOULDER = 11;
const RIGHT_SHOULDER = 12;

/** Upper-body skeleton drawn over the self-view (hips/legs are not drawn). */
export const POSE_OVERLAY_CONNECTIONS: ReadonlyArray<readonly [number, number]> = [
  [11, 12],
  [11, 13],
  [13, 15],
  [12, 14],
  [14, 16],
  [0, 2],
  [0, 5],
  [2, 7],
  [5, 8],
  [9, 10],
  [11, 23],
  [12, 24],
  [23, 24],
];
export const POSE_OVERLAY_POINTS: readonly number[] = [0, 2, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 23, 24];

// ---------------------------------------------------------------------------
// Tunables
// ---------------------------------------------------------------------------

export const POSTURE_TUNING = {
  minVisibility: 0.5,
  /** A gap in updates longer than this counts as this much (tab throttling, etc.). */
  maxStepMs: 1000,
  featureTauMs: 500,
  positionTauMs: 300,
  noTrackingAfterMs: 2000,
  calibrationMinSamples: 12,
  calibrationMinSpanMs: 3000,
  motionWindowMs: 4000,
  motionMinSamples: 8,
  minMessageDisplayMs: 2500,
  /** Scored time needed before a summary or live consistency figure is shown. */
  minScoredMsForSummary: 15_000,
  minScoredMsForLive: 10_000,
  // Framing, as fractions of the frame.
  tooCloseWidth: 0.62,
  tooFarWidth: 0.14,
  offCenter: 0.22,
  edgeMargin: 0.02,
  headTopMargin: 0.03,
  // Lighting (mean luma 0-255 over the centre of the frame).
  dimLuma: 55,
  brightLuma: 70,
  dimEnterMs: 3000,
  dimExitMs: 2000,
} as const;

interface IssueSpec {
  enterMs: number;
  exitMs: number;
  priority: number;
  label: string;
  tip: string;
}

export const POSTURE_ISSUES: Record<PostureIssueId, IssueSpec> = {
  framing: {
    enterMs: 2000,
    exitMs: 1500,
    priority: 0,
    label: "Camera framing",
    tip: "Frame the camera so your head and both shoulders are visible and centred.",
  },
  slouch: {
    enterMs: 2500,
    exitMs: 1500,
    priority: 1,
    label: "Back posture",
    tip: "Sit tall with your back supported and lift the crown of your head.",
  },
  forward_head: {
    enterMs: 2500,
    exitMs: 1500,
    priority: 2,
    label: "Head position",
    tip: "Tuck your chin slightly and keep your head over your shoulders, not leaning toward the screen.",
  },
  head_tilt: {
    enterMs: 2000,
    exitMs: 1500,
    priority: 3,
    label: "Head alignment",
    tip: "Keep your head level and centred above your shoulders.",
  },
  uneven_shoulders: {
    enterMs: 2500,
    exitMs: 1500,
    priority: 4,
    label: "Shoulder level",
    tip: "Drop and relax your shoulders; check your chair and desk height if one side keeps rising.",
  },
  movement: {
    enterMs: 1500,
    exitMs: 2000,
    priority: 5,
    label: "Movement",
    tip: "Try to settle into a steady position while you answer.",
  },
};

const ISSUE_IDS = Object.keys(POSTURE_ISSUES) as PostureIssueId[];

const ISSUE_MESSAGES: Record<Exclude<PostureIssueId, "framing">, string> = {
  slouch: "Straighten your back",
  forward_head: "Keep your head aligned — tuck your chin back",
  head_tilt: "Keep your head aligned — level it over your shoulders",
  uneven_shoulders: "Relax your shoulders and level them",
  movement: "Try to stay a little steadier",
};

export const FRAMING_MESSAGES: Record<FramingProblem, string> = {
  shoulders_cut: "Move so both of your shoulders are in view",
  head_cut: "Lower the camera or sit back so your head isn't cut off",
  too_close: "Sit back a little so your shoulders fit in view",
  too_far: "Move a bit closer to the camera",
  off_center: "Move to the middle of the camera view",
};

export const NO_TRACKING_MESSAGE =
  "We can't see your head and shoulders — move into the camera view";
export const NO_TRACKING_DARK_MESSAGE =
  "It looks too dark to track you — add some light in front of you";
export const CALIBRATING_MESSAGE = "Calibrating — sit upright and look at the camera";

// ---------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------

function visibilityOf(point: PoseLandmark | undefined): number {
  if (!point) return 0;
  const value = point.visibility ?? point.presence ?? 0;
  return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
}

function dist(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function mid(a: Point, b: Point): Point {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

/** Angle of the line a→b away from horizontal, in degrees, folded to 0-90. */
function tiltDegrees(a: Point, b: Point): number {
  return (Math.atan2(Math.abs(a.y - b.y), Math.abs(a.x - b.x)) * 180) / Math.PI;
}

function median(values: number[]): number {
  const sorted = [...values].sort((x, y) => x - y);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function smooth(previous: number | null, next: number | null, dtMs: number, tauMs: number): number | null {
  if (next === null || !Number.isFinite(next)) return null;
  if (previous === null || dtMs <= 0) return next;
  const alpha = 1 - Math.exp(-dtMs / tauMs);
  return previous + alpha * (next - previous);
}

export interface PostureFeatures {
  /** Shoulder width in frame-width units (camera-distance proxy). */
  shoulderWidth: number;
  shoulderMid: Point;
  /** Ear midpoint when both ears are visible, else the nose. In frame-width units. */
  headPoint: Point | null;
  /** Shoulder-line tilt from horizontal, degrees. */
  shoulderTiltDeg: number;
  /** |ear midpoint − shoulder midpoint| horizontally, in shoulder widths. */
  headOffset: number | null;
  /** Ear-line tilt from horizontal, degrees. */
  earTiltDeg: number | null;
  /** Vertical ear→shoulder-line distance, in shoulder widths (shrinks when slumping). */
  neckRatio: number | null;
  /** Ear-to-ear distance, in shoulder widths (grows when the head pushes toward the camera). */
  earSpan: number | null;
  framing: FramingProblem | null;
}

/**
 * Per-frame measurements from one pose. Returns null when there is nothing
 * usable (no pose, or neither the head nor the shoulders are visible).
 *
 * `aspect` is videoHeight / videoWidth: MediaPipe normalises x by width and y by
 * height, so y must be rescaled before distances and angles mean anything.
 */
export function extractPostureFeatures(
  landmarks: readonly PoseLandmark[] | undefined | null,
  aspect = 9 / 16,
): PostureFeatures | null {
  if (!landmarks || landmarks.length <= RIGHT_SHOULDER) return null;
  const min = POSTURE_TUNING.minVisibility;
  const nose = landmarks[NOSE];
  const ls = landmarks[LEFT_SHOULDER];
  const rs = landmarks[RIGHT_SHOULDER];
  const earL = landmarks[LEFT_EAR];
  const earR = landmarks[RIGHT_EAR];

  const shouldersVisible = visibilityOf(ls) >= min && visibilityOf(rs) >= min;
  const headVisible = visibilityOf(nose) >= min;
  if (!shouldersVisible && !headVisible) return null;

  const px = (p: PoseLandmark): Point => ({ x: p.x, y: p.y * aspect });

  if (!shouldersVisible) {
    // The head is there but the shoulders are cropped out of the frame.
    return {
      shoulderWidth: 0,
      shoulderMid: { x: nose.x, y: nose.y * aspect },
      headPoint: px(nose),
      shoulderTiltDeg: 0,
      headOffset: null,
      earTiltDeg: null,
      neckRatio: null,
      earSpan: null,
      framing: "shoulders_cut",
    };
  }

  const lsP = px(ls);
  const rsP = px(rs);
  const width = dist(lsP, rsP);
  if (width < 0.03) return null; // degenerate: shoulders collapsed onto each other

  const shoulderMid = mid(lsP, rsP);
  const earsVisible = visibilityOf(earL) >= min && visibilityOf(earR) >= min;
  const earMid = earsVisible ? mid(px(earL), px(earR)) : null;
  const headPoint = earMid ?? (headVisible ? px(nose) : null);

  const inFrame = (p: PoseLandmark) =>
    p.x >= POSTURE_TUNING.edgeMargin &&
    p.x <= 1 - POSTURE_TUNING.edgeMargin &&
    p.y >= 0 &&
    p.y <= 1 - POSTURE_TUNING.edgeMargin;

  let framing: FramingProblem | null = null;
  if (!inFrame(ls) || !inFrame(rs)) framing = "shoulders_cut";
  else if (
    (headVisible && nose.y < POSTURE_TUNING.headTopMargin) ||
    (earsVisible && (earL.y < 0.01 || earR.y < 0.01))
  )
    framing = "head_cut";
  else if (width > POSTURE_TUNING.tooCloseWidth) framing = "too_close";
  else if (width < POSTURE_TUNING.tooFarWidth) framing = "too_far";
  else if (Math.abs((ls.x + rs.x) / 2 - 0.5) > POSTURE_TUNING.offCenter) framing = "off_center";

  return {
    shoulderWidth: width,
    shoulderMid,
    headPoint,
    shoulderTiltDeg: tiltDegrees(lsP, rsP),
    headOffset: earMid ? Math.abs(earMid.x - shoulderMid.x) / width : null,
    earTiltDeg: earsVisible ? tiltDegrees(px(earL), px(earR)) : null,
    neckRatio: earMid ? (shoulderMid.y - earMid.y) / width : null,
    earSpan: earsVisible ? dist(px(earL), px(earR)) / width : null,
    framing,
  };
}

/** Mean brightness (0-255) of the central half of an RGBA image. Pure helper for the lighting check. */
export function meanLumaOfRgba(data: ArrayLike<number>, width: number, height: number): number | null {
  if (width <= 0 || height <= 0 || data.length < width * height * 4) return null;
  const x0 = Math.floor(width * 0.25);
  const x1 = Math.ceil(width * 0.75);
  const y0 = Math.floor(height * 0.25);
  const y1 = Math.ceil(height * 0.75);
  let sum = 0;
  let count = 0;
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      const i = (y * width + x) * 4;
      sum += 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
      count += 1;
    }
  }
  return count ? sum / count : null;
}

/**
 * Where a normalised landmark lands on a box that shows the video with
 * `object-fit: cover` (the self-view crops rather than letterboxes).
 */
export function mapPointToCoverBox(
  point: Point,
  video: { width: number; height: number },
  box: { width: number; height: number },
): Point {
  const scale = Math.max(box.width / video.width, box.height / video.height);
  const offsetX = (box.width - video.width * scale) / 2;
  const offsetY = (box.height - video.height * scale) / 2;
  return { x: point.x * video.width * scale + offsetX, y: point.y * video.height * scale + offsetY };
}

// ---------------------------------------------------------------------------
// Engine
// ---------------------------------------------------------------------------

export interface PostureSnapshot {
  status: PostureStatus;
  /** Active (debounced) issues, highest priority first. */
  issues: PostureIssueId[];
  /** The one corrective message to show now, or the calibration / tracking hint. */
  message: string | null;
  /** Messages for every active issue. */
  messages: string[];
  lighting: LightingState;
  calibrated: boolean;
  /** Share of scored time spent in good posture so far (0-1); null until enough time has passed. */
  consistency: number | null;
}

export interface PostureSessionSummary {
  scoredSeconds: number;
  consistencyPercent: number;
  rating: PostureRating;
  headline: string;
  issues: { id: PostureIssueId; label: string; percent: number; episodes: number; tip: string }[];
  trackingLostPercent: number;
  dimLightingPercent: number;
  notes: string[];
}

interface IssueState {
  active: boolean;
  rawSince: number | null;
  clearSince: number | null;
  episodes: number;
  activeMs: number;
}

interface Baseline {
  neckRatio: number | null;
  earSpan: number | null;
  shoulderWidth: number;
}

interface Totals {
  goodMs: number;
  needsMs: number;
  calibratingMs: number;
  lostMs: number;
  dimMs: number;
}

export interface PostureUpdateOptions {
  /** videoHeight / videoWidth of the frame the landmarks came from. */
  aspect?: number;
  /** Mean frame brightness 0-255, if measured this tick. */
  luma?: number | null;
}

export class PostureEngine {
  private issueStates!: Record<PostureIssueId, IssueState>;
  private totals!: Totals;
  private baseline: Baseline | null = null;
  private calibrationSamples: { t: number; neck: number | null; span: number | null; width: number }[] = [];
  private lastT: number | null = null;
  private lostForMs = 0;
  private smoothed!: {
    tilt: number | null;
    headOffset: number | null;
    earTilt: number | null;
    neck: number | null;
    earSpan: number | null;
    width: number | null;
  };
  private motion: { t: number; shoulder: Point; head: Point | null }[] = [];
  private smoothedShoulder: Point | null = null;
  private smoothedHead: Point | null = null;
  private framingProblem: FramingProblem | null = null;
  private shown: { id: PostureIssueId; since: number } | null = null;
  private lighting: LightingState = "unknown";
  private dimSince: number | null = null;
  private brightSince: number | null = null;
  private last: PostureSnapshot;

  constructor() {
    this.reset();
    this.last = this.buildSnapshot("calibrating", [], CALIBRATING_MESSAGE);
  }

  /** Forget everything (new session / consent revoked). */
  reset(): void {
    this.issueStates = Object.fromEntries(
      ISSUE_IDS.map((id) => [id, { active: false, rawSince: null, clearSince: null, episodes: 0, activeMs: 0 }]),
    ) as Record<PostureIssueId, IssueState>;
    this.totals = { goodMs: 0, needsMs: 0, calibratingMs: 0, lostMs: 0, dimMs: 0 };
    this.baseline = null;
    this.calibrationSamples = [];
    this.lastT = null;
    this.lostForMs = 0;
    this.smoothed = { tilt: null, headOffset: null, earTilt: null, neck: null, earSpan: null, width: null };
    this.motion = [];
    this.smoothedShoulder = null;
    this.smoothedHead = null;
    this.framingProblem = null;
    this.shown = null;
    this.lighting = "unknown";
    this.dimSince = null;
    this.brightSince = null;
  }

  /**
   * Start a fresh upright baseline (the candidate sat differently, moved the
   * camera, or the first reading was taken while slouching). Session totals
   * already collected are kept.
   */
  recalibrate(): void {
    this.baseline = null;
    this.calibrationSamples = [];
    for (const id of ISSUE_IDS) {
      const state = this.issueStates[id];
      state.active = false;
      state.rawSince = null;
      state.clearSince = null;
    }
    this.shown = null;
  }

  isCalibrated(): boolean {
    return this.baseline !== null;
  }

  getSnapshot(): PostureSnapshot {
    return this.last;
  }

  /**
   * Feed one pose result. `nowMs` must be monotonic (performance.now()).
   * Pass `undefined` landmarks when no pose was detected this tick.
   */
  update(
    landmarks: readonly PoseLandmark[] | undefined | null,
    nowMs: number,
    options: PostureUpdateOptions = {},
  ): PostureSnapshot {
    const dt = this.lastT === null ? 0 : Math.max(0, Math.min(nowMs - this.lastT, POSTURE_TUNING.maxStepMs));
    this.lastT = nowMs;
    this.updateLighting(nowMs, dt, options.luma);

    const features = extractPostureFeatures(landmarks, options.aspect);
    if (!features) return this.handleLost(dt);

    this.lostForMs = 0;
    this.framingProblem = features.framing ?? this.framingProblem;
    this.smoothFeatures(features, dt);
    this.updateMotion(features, nowMs, dt);

    const motionSpread = this.motionSpread();
    this.collectCalibration(features, nowMs, motionSpread);
    const raw = this.detectRaw(features, motionSpread);
    this.applyDebounce(raw, nowMs, dt);

    const active = ISSUE_IDS.filter((id) => this.issueStates[id].active).sort(
      (a, b) => POSTURE_ISSUES[a].priority - POSTURE_ISSUES[b].priority,
    );

    if (this.baseline) {
      if (active.length) this.totals.needsMs += dt;
      else this.totals.goodMs += dt;
    } else {
      this.totals.calibratingMs += dt;
    }

    const status: PostureStatus = active.length ? "needs_correction" : this.baseline ? "good" : "calibrating";
    const message = this.pickMessage(active, nowMs) ?? (status === "calibrating" ? CALIBRATING_MESSAGE : null);
    this.last = this.buildSnapshot(status, active, message);
    return this.last;
  }

  /** Session-level summary of everything observed so far, or null when there isn't enough data. */
  getSummary(): PostureSessionSummary | null {
    const scoredMs = this.totals.goodMs + this.totals.needsMs;
    if (scoredMs < POSTURE_TUNING.minScoredMsForSummary) return null;

    const pct = (ms: number, of: number) => (of > 0 ? Math.round((ms / of) * 100) : 0);
    const consistencyPercent = pct(this.totals.goodMs, scoredMs);
    const rating: PostureRating =
      consistencyPercent >= 85 ? "consistent" : consistencyPercent >= 60 ? "mostly_consistent" : "needs_attention";
    const headline =
      rating === "consistent"
        ? "Your posture stayed consistent for most of the session."
        : rating === "mostly_consistent"
          ? "Your posture was mostly consistent, with some moments to tidy up."
          : "Your posture needed correction for a good part of the session.";

    const issues = ISSUE_IDS.map((id) => ({
      id,
      label: POSTURE_ISSUES[id].label,
      percent: pct(this.issueStates[id].activeMs, scoredMs),
      episodes: this.issueStates[id].episodes,
      tip: POSTURE_ISSUES[id].tip,
    }))
      .filter((issue) => issue.percent >= 5 || issue.episodes >= 3)
      .sort((a, b) => b.percent - a.percent || b.episodes - a.episodes);

    const cameraMs = scoredMs + this.totals.calibratingMs + this.totals.lostMs;
    const trackingLostPercent = pct(this.totals.lostMs, cameraMs);
    const dimLightingPercent = pct(this.totals.dimMs, cameraMs);

    const notes: string[] = [];
    if (trackingLostPercent >= 15)
      notes.push(
        `Your head and shoulders couldn't be tracked for about ${trackingLostPercent}% of the time the camera was on.`,
      );
    if (dimLightingPercent >= 30)
      notes.push("The lighting looked dim for much of the session, which makes tracking less reliable.");
    notes.push(
      "These are rough, camera-based estimates for practice only. They are not a medical assessment and are not part of your interview score.",
    );

    return {
      scoredSeconds: Math.round(scoredMs / 1000),
      consistencyPercent,
      rating,
      headline,
      issues,
      trackingLostPercent,
      dimLightingPercent,
      notes,
    };
  }

  // ----------------------------------------------------------------- internals

  private buildSnapshot(status: PostureStatus, active: PostureIssueId[], message: string | null): PostureSnapshot {
    const scoredMs = this.totals.goodMs + this.totals.needsMs;
    return {
      status,
      issues: active,
      message,
      messages: active.map((id) => this.messageFor(id)),
      lighting: this.lighting,
      calibrated: this.baseline !== null,
      consistency: scoredMs >= POSTURE_TUNING.minScoredMsForLive ? this.totals.goodMs / scoredMs : null,
    };
  }

  private messageFor(id: PostureIssueId): string {
    if (id === "framing") return FRAMING_MESSAGES[this.framingProblem ?? "off_center"];
    return ISSUE_MESSAGES[id];
  }

  private pickMessage(active: PostureIssueId[], nowMs: number): string | null {
    const top = active[0] ?? null;
    if (!this.shown || !this.issueStates[this.shown.id].active) {
      this.shown = top ? { id: top, since: nowMs } : null;
    } else if (top && top !== this.shown.id && nowMs - this.shown.since >= POSTURE_TUNING.minMessageDisplayMs) {
      this.shown = { id: top, since: nowMs };
    }
    return this.shown ? this.messageFor(this.shown.id) : null;
  }

  private handleLost(dt: number): PostureSnapshot {
    this.lostForMs += dt;
    if (this.lostForMs >= 1000) {
      // Positions are no longer continuous with what came before.
      this.motion = [];
      this.smoothedShoulder = null;
      this.smoothedHead = null;
      this.calibrationSamples = [];
    }
    if (this.lostForMs < POSTURE_TUNING.noTrackingAfterMs) {
      // A brief dropout: hold the last answer rather than flashing a warning.
      this.last = { ...this.last, lighting: this.lighting };
      return this.last;
    }
    this.totals.lostMs += dt;
    for (const id of ISSUE_IDS) this.issueStates[id].rawSince = null;
    this.last = this.buildSnapshot(
      "no_tracking",
      [],
      this.lighting === "dim" ? NO_TRACKING_DARK_MESSAGE : NO_TRACKING_MESSAGE,
    );
    return this.last;
  }

  private updateLighting(nowMs: number, dt: number, luma: number | null | undefined): void {
    if (luma === undefined) {
      if (this.lighting === "dim") this.totals.dimMs += dt;
      return;
    }
    if (luma === null) {
      this.lighting = "unknown";
      this.dimSince = this.brightSince = null;
      return;
    }
    if (luma < POSTURE_TUNING.dimLuma) {
      this.brightSince = null;
      this.dimSince ??= nowMs;
      if (nowMs - this.dimSince >= POSTURE_TUNING.dimEnterMs) this.lighting = "dim";
    } else if (luma >= POSTURE_TUNING.brightLuma) {
      this.dimSince = null;
      this.brightSince ??= nowMs;
      if (this.lighting !== "ok" && nowMs - this.brightSince >= POSTURE_TUNING.dimExitMs) this.lighting = "ok";
      if (this.lighting === "unknown") this.lighting = "ok";
    }
    if (this.lighting === "dim") this.totals.dimMs += dt;
  }

  private smoothFeatures(f: PostureFeatures, dt: number): void {
    const tau = POSTURE_TUNING.featureTauMs;
    const s = this.smoothed;
    const valid = f.framing === null || f.framing !== "shoulders_cut";
    s.tilt = valid ? smooth(s.tilt, f.shoulderTiltDeg, dt, tau) : null;
    s.headOffset = smooth(s.headOffset, f.headOffset, dt, tau);
    s.earTilt = smooth(s.earTilt, f.earTiltDeg, dt, tau);
    s.neck = smooth(s.neck, f.neckRatio, dt, tau);
    s.earSpan = smooth(s.earSpan, f.earSpan, dt, tau);
    s.width = valid ? smooth(s.width, f.shoulderWidth, dt, tau) : null;
  }

  private updateMotion(f: PostureFeatures, nowMs: number, dt: number): void {
    if (f.framing === "shoulders_cut") return;
    const tau = POSTURE_TUNING.positionTauMs;
    const blend = (prev: Point | null, next: Point): Point =>
      prev === null || dt <= 0
        ? next
        : {
            x: prev.x + (1 - Math.exp(-dt / tau)) * (next.x - prev.x),
            y: prev.y + (1 - Math.exp(-dt / tau)) * (next.y - prev.y),
          };
    this.smoothedShoulder = blend(this.smoothedShoulder, f.shoulderMid);
    this.smoothedHead = f.headPoint ? blend(this.smoothedHead, f.headPoint) : null;
    this.motion.push({ t: nowMs, shoulder: this.smoothedShoulder, head: this.smoothedHead });
    const cutoff = nowMs - POSTURE_TUNING.motionWindowMs;
    while (this.motion.length && this.motion[0].t < cutoff) this.motion.shift();
  }

  /** RMS wander of head/shoulders over the recent window, in shoulder widths; null if too little data. */
  private motionSpread(): number | null {
    const samples = this.motion;
    const width = this.smoothed.width;
    if (samples.length < POSTURE_TUNING.motionMinSamples || !width) return null;
    if (samples[samples.length - 1].t - samples[0].t < 2000) return null;
    const spreadOf = (points: Point[]) => {
      const cx = points.reduce((sum, p) => sum + p.x, 0) / points.length;
      const cy = points.reduce((sum, p) => sum + p.y, 0) / points.length;
      return Math.sqrt(points.reduce((sum, p) => sum + (p.x - cx) ** 2 + (p.y - cy) ** 2, 0) / points.length);
    };
    const shoulderSpread = spreadOf(samples.map((s) => s.shoulder));
    const heads = samples.map((s) => s.head).filter((p): p is Point => p !== null);
    const headSpread = heads.length >= POSTURE_TUNING.motionMinSamples ? spreadOf(heads) : 0;
    return Math.max(shoulderSpread, headSpread) / width;
  }

  private collectCalibration(f: PostureFeatures, nowMs: number, spread: number | null): void {
    if (this.baseline || f.framing !== null) return;
    const s = this.smoothed;
    // Only learn from a calm, level, well-framed moment.
    if ((s.tilt ?? 0) > 6 || (s.headOffset ?? 0) > 0.3 || (spread ?? 0) > 0.12) {
      this.calibrationSamples = [];
      return;
    }
    this.calibrationSamples.push({ t: nowMs, neck: s.neck, span: s.earSpan, width: f.shoulderWidth });
    const samples = this.calibrationSamples;
    if (
      samples.length < POSTURE_TUNING.calibrationMinSamples ||
      samples[samples.length - 1].t - samples[0].t < POSTURE_TUNING.calibrationMinSpanMs
    )
      return;
    const pick = (values: (number | null)[]) => {
      const present = values.filter((v): v is number => v !== null);
      return present.length >= samples.length * 0.6 ? median(present) : null;
    };
    this.baseline = {
      neckRatio: pick(samples.map((x) => x.neck)),
      earSpan: pick(samples.map((x) => x.span)),
      shoulderWidth: median(samples.map((x) => x.width)),
    };
    this.calibrationSamples = [];
  }

  private detectRaw(f: PostureFeatures, spread: number | null): Record<PostureIssueId, boolean> {
    const was = (id: PostureIssueId) => this.issueStates[id].active;
    const s = this.smoothed;
    const framingBad = f.framing !== null;
    const b = this.baseline;

    // While the frame itself is wrong, geometry-based judgements aren't trustworthy.
    const geometry = !framingBad;
    const neckRelative = b?.neckRatio && s.neck !== null ? s.neck / b.neckRatio : null;
    const spanRelative = b?.earSpan && s.earSpan !== null ? s.earSpan / b.earSpan : null;
    const widthRelative = b && s.width !== null ? s.width / b.shoulderWidth : null;

    return {
      framing: framingBad,
      uneven_shoulders: geometry && s.tilt !== null && s.tilt > (was("uneven_shoulders") ? 5.5 : 8),
      head_tilt:
        geometry &&
        ((s.headOffset !== null && s.headOffset > (was("head_tilt") ? 0.28 : 0.4)) ||
          (s.earTilt !== null && s.earTilt > (was("head_tilt") ? 8 : 12))),
      slouch: geometry && neckRelative !== null && neckRelative < (was("slouch") ? 0.88 : 0.8),
      forward_head:
        geometry &&
        ((spanRelative !== null && spanRelative > (was("forward_head") ? 1.07 : 1.12)) ||
          (widthRelative !== null && widthRelative > (was("forward_head") ? 1.12 : 1.22))),
      movement: geometry && spread !== null && spread > (was("movement") ? 0.1 : 0.18),
    };
  }

  private applyDebounce(raw: Record<PostureIssueId, boolean>, nowMs: number, dt: number): void {
    for (const id of ISSUE_IDS) {
      const state = this.issueStates[id];
      const spec = POSTURE_ISSUES[id];
      if (raw[id]) {
        state.clearSince = null;
        state.rawSince ??= nowMs;
        if (!state.active && nowMs - state.rawSince >= spec.enterMs) {
          state.active = true;
          state.episodes += 1;
        }
      } else {
        state.rawSince = null;
        if (state.active) {
          state.clearSince ??= nowMs;
          if (nowMs - state.clearSince >= spec.exitMs) {
            state.active = false;
            state.clearSince = null;
          }
        }
      }
      if (state.active && this.baseline) state.activeMs += dt;
    }
  }
}
