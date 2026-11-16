import { describe, expect, it } from "vitest";
import {
  extractPostureFeatures,
  mapPointToCoverBox,
  meanLumaOfRgba,
  PostureEngine,
  type PoseLandmark,
} from "@/lib/posture";

const ASPECT = 9 / 16;
const STEP_MS = 200; // ~5 fps, like the live tracker

interface PoseOptions {
  shiftX?: number;
  leftShoulderY?: number;
  rightShoulderY?: number;
  earY?: number;
  visibility?: number;
}

/** A head-and-shoulders pose (no hips), upright by default. */
function pose(options: PoseOptions = {}): PoseLandmark[] {
  const { shiftX = 0, leftShoulderY = 0.55, rightShoulderY = 0.55, earY = 0.4, visibility = 0.9 } = options;
  const points: PoseLandmark[] = Array.from({ length: 33 }, () => ({ x: 0.5, y: 0.5, visibility: 0.1 }));
  const set = (index: number, x: number, y: number) => {
    points[index] = { x: x + shiftX, y, visibility };
  };
  set(0, 0.5, 0.33); // nose
  set(2, 0.48, 0.3);
  set(5, 0.52, 0.3);
  set(7, 0.45, earY); // ears
  set(8, 0.55, earY);
  set(11, 0.4, leftShoulderY); // shoulders: 0.2 of the frame wide
  set(12, 0.6, rightShoulderY);
  return points;
}

function run(
  engine: PostureEngine,
  startMs: number,
  seconds: number,
  frame: (tMs: number) => PoseLandmark[] | undefined,
) {
  let t = startMs;
  let snapshot = engine.getSnapshot();
  const end = startMs + seconds * 1000;
  while (t < end) {
    snapshot = engine.update(frame(t), t, { aspect: ASPECT });
    t += STEP_MS;
  }
  return { t, snapshot };
}

function calibrated(engine = new PostureEngine()) {
  const { t, snapshot } = run(engine, 0, 5, () => pose());
  expect(snapshot.status).toBe("good");
  return { engine, t };
}

describe("extractPostureFeatures", () => {
  it("measures an upright head-and-shoulders pose without needing hips", () => {
    const f = extractPostureFeatures(pose(), ASPECT)!;
    expect(f.framing).toBeNull();
    expect(f.shoulderWidth).toBeCloseTo(0.2);
    expect(f.shoulderTiltDeg).toBeCloseTo(0);
    expect(f.headOffset).toBeCloseTo(0);
    expect(f.neckRatio).toBeGreaterThan(0.3);
  });

  it("returns null when nothing is visible", () => {
    expect(extractPostureFeatures(pose({ visibility: 0.05 }), ASPECT)).toBeNull();
    expect(extractPostureFeatures(undefined, ASPECT)).toBeNull();
  });

  it("flags shoulders that are cropped out of the frame", () => {
    const points = pose();
    points[11] = { x: 0.4, y: 0.55, visibility: 0.1 };
    expect(extractPostureFeatures(points, ASPECT)?.framing).toBe("shoulders_cut");
  });

  it("flags too close, too far and off-centre framing", () => {
    const wide = pose();
    wide[11] = { x: 0.15, y: 0.55, visibility: 0.9 };
    wide[12] = { x: 0.85, y: 0.55, visibility: 0.9 };
    expect(extractPostureFeatures(wide, ASPECT)?.framing).toBe("too_close");

    const narrow = pose();
    narrow[11] = { x: 0.46, y: 0.55, visibility: 0.9 };
    narrow[12] = { x: 0.54, y: 0.55, visibility: 0.9 };
    expect(extractPostureFeatures(narrow, ASPECT)?.framing).toBe("too_far");

    expect(extractPostureFeatures(pose({ shiftX: 0.3 }), ASPECT)?.framing).toBe("off_center");
  });

  it("accounts for the frame's aspect ratio when measuring tilt", () => {
    const tilted = pose({ leftShoulderY: 0.5, rightShoulderY: 0.6 });
    const wideFrame = extractPostureFeatures(tilted, 9 / 16)!.shoulderTiltDeg;
    const squareFrame = extractPostureFeatures(tilted, 1)!.shoulderTiltDeg;
    expect(squareFrame).toBeGreaterThan(wideFrame);
  });
});

describe("PostureEngine", () => {
  it("calibrates on the candidate's own upright posture, then reports Good", () => {
    const engine = new PostureEngine();
    const early = run(engine, 0, 1.5, () => pose());
    expect(early.snapshot.status).toBe("calibrating");
    expect(early.snapshot.message).toMatch(/calibrating/i);
    const later = run(engine, early.t, 4, () => pose());
    expect(later.snapshot.status).toBe("good");
    expect(later.snapshot.calibrated).toBe(true);
    expect(later.snapshot.issues).toEqual([]);
  });

  it("asks the candidate to straighten up when they slump, and clears once they recover", () => {
    const { engine, t } = calibrated();
    const slumped = run(engine, t, 4, () => pose({ earY: 0.5 }));
    expect(slumped.snapshot.status).toBe("needs_correction");
    expect(slumped.snapshot.issues).toContain("slouch");
    expect(slumped.snapshot.message).toBe("Straighten your back");

    const recovered = run(engine, slumped.t, 4, () => pose());
    expect(recovered.snapshot.status).toBe("good");
  });

  it("does not flicker on a momentary blip", () => {
    const { engine, t } = calibrated();
    const blip = run(engine, t, 0.6, () => pose({ earY: 0.5 }));
    expect(blip.snapshot.status).toBe("good");
    const after = run(engine, blip.t, 3, () => pose());
    expect(after.snapshot.status).toBe("good");
    expect(engine.getSnapshot().issues).toEqual([]);
  });

  it("flags uneven shoulders with a relax message", () => {
    const { engine, t } = calibrated();
    const { snapshot } = run(engine, t, 4, () => pose({ leftShoulderY: 0.5, rightShoulderY: 0.62 }));
    expect(snapshot.issues).toContain("uneven_shoulders");
    expect(snapshot.messages.join(" ")).toMatch(/relax your shoulders/i);
  });

  it("flags excessive movement but not stillness", () => {
    const { engine, t } = calibrated();
    const still = run(engine, t, 6, () => pose());
    expect(still.snapshot.issues).not.toContain("movement");
    const swaying = run(engine, still.t, 8, (ms) => pose({ shiftX: 0.08 * Math.sin((2 * Math.PI * ms) / 2000) }));
    expect(swaying.snapshot.issues).toContain("movement");
  });

  it("reports framing problems with a specific instruction and suspends posture judgements", () => {
    const { engine, t } = calibrated();
    const { snapshot } = run(engine, t, 4, () => pose({ shiftX: 0.3 }));
    expect(snapshot.status).toBe("needs_correction");
    expect(snapshot.issues[0]).toBe("framing");
    expect(snapshot.message).toMatch(/middle of the camera view/i);
  });

  it("rides out a brief tracking dropout but reports a sustained one", () => {
    const { engine, t } = calibrated();
    const brief = run(engine, t, 1, () => undefined);
    expect(brief.snapshot.status).toBe("good");
    const lost = run(engine, brief.t, 3, () => undefined);
    expect(lost.snapshot.status).toBe("no_tracking");
    expect(lost.snapshot.message).toMatch(/can't see your head and shoulders/i);
    const back = run(engine, lost.t, 1, () => pose());
    expect(back.snapshot.status).not.toBe("no_tracking");
  });

  it("mentions darkness when tracking is lost in dim light", () => {
    const engine = new PostureEngine();
    let t = 0;
    for (; t < 8000; t += STEP_MS) engine.update(undefined, t, { aspect: ASPECT, luma: 20 });
    const snapshot = engine.getSnapshot();
    expect(snapshot.lighting).toBe("dim");
    expect(snapshot.status).toBe("no_tracking");
    expect(snapshot.message).toMatch(/too dark/i);
  });

  it("builds a session summary only once there is enough data", () => {
    const { engine, t } = calibrated();
    expect(engine.getSummary()).toBeNull();
    const good = run(engine, t, 20, () => pose());
    run(engine, good.t, 10, () => pose({ earY: 0.5 }));
    const summary = engine.getSummary()!;
    expect(summary.scoredSeconds).toBeGreaterThanOrEqual(15);
    expect(summary.consistencyPercent).toBeGreaterThan(40);
    expect(summary.consistencyPercent).toBeLessThan(100);
    expect(summary.issues.map((issue) => issue.id)).toContain("slouch");
    expect(summary.notes.join(" ")).toMatch(/not part of your interview score/i);
  });

  it("recalibrates to a new baseline without losing the session totals", () => {
    const { engine, t } = calibrated();
    run(engine, t, 20, () => pose());
    engine.recalibrate();
    expect(engine.isCalibrated()).toBe(false);
    expect(engine.getSummary()).not.toBeNull();
    // The slumped position becomes the new "upright".
    const { snapshot } = run(engine, t + 20_000, 6, () => pose({ earY: 0.5 }));
    expect(snapshot.status).toBe("good");
  });

  it("reset forgets everything", () => {
    const { engine } = calibrated();
    engine.reset();
    expect(engine.isCalibrated()).toBe(false);
    expect(engine.getSummary()).toBeNull();
  });
});

describe("helpers", () => {
  it("averages the brightness of the centre of an RGBA image", () => {
    const width = 4;
    const height = 4;
    const data = new Uint8ClampedArray(width * height * 4).fill(255);
    expect(meanLumaOfRgba(data, width, height)).toBeCloseTo(255);
    data.fill(0);
    expect(meanLumaOfRgba(data, width, height)).toBe(0);
    expect(meanLumaOfRgba(new Uint8ClampedArray(3), width, height)).toBeNull();
  });

  it("maps landmarks through the object-cover crop of the self-view", () => {
    // A 4:3 video shown in a 16:9 box is scaled to the box width and cropped top/bottom.
    const point = mapPointToCoverBox({ x: 0.5, y: 0.5 }, { width: 640, height: 480 }, { width: 320, height: 180 });
    expect(point.x).toBeCloseTo(160);
    expect(point.y).toBeCloseTo(90);
    const corner = mapPointToCoverBox({ x: 0, y: 0 }, { width: 640, height: 480 }, { width: 320, height: 180 });
    expect(corner.x).toBeCloseTo(0);
    expect(corner.y).toBeLessThan(0);
  });
});
