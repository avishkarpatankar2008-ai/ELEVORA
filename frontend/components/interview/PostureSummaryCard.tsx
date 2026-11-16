import { Card } from "@/components/Card";
import { Badge, type BadgeTone } from "@/components/Badge";
import type { PostureRating, PostureSessionSummary } from "@/lib/posture";

const RATING_LABEL: Record<PostureRating, string> = {
  consistent: "Consistent",
  mostly_consistent: "Mostly consistent",
  needs_attention: "Needs attention",
};
const RATING_TONE: Record<PostureRating, BadgeTone> = {
  consistent: "success",
  mostly_consistent: "blue",
  needs_attention: "warning",
};

/**
 * Session-level posture observations. Computed on this device from the live
 * posture estimates; shown only here and never mixed into the interview score.
 */
export function PostureSummaryCard({ summary }: { summary: PostureSessionSummary }) {
  return (
    <Card className="mt-6" data-testid="posture-summary">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-sm font-semibold text-ink">Posture observations</h2>
        <Badge tone={RATING_TONE[summary.rating]}>{RATING_LABEL[summary.rating]}</Badge>
        <Badge>Not scored</Badge>
      </div>
      <p className="mt-3 text-sm leading-6 text-ink-soft">
        {summary.headline} You were in good posture for {summary.consistencyPercent}% of the{" "}
        {summary.scoredSeconds} seconds that were measured.
      </p>

      {summary.issues.length > 0 && (
        <ul className="mt-3 space-y-2 text-sm text-ink-soft">
          {summary.issues.map((issue) => (
            <li key={issue.id}>
              <span className="font-medium text-ink">{issue.label}:</span> flagged for{" "}
              {issue.percent}% of the time ({issue.episodes} time{issue.episodes === 1 ? "" : "s"}).{" "}
              <span className="text-ink-mute">{issue.tip}</span>
            </li>
          ))}
        </ul>
      )}

      <ul className="mt-3 space-y-1 text-xs leading-5 text-ink-mute">
        {summary.notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
        <li>Computed in your browser. No camera frames or landmarks were uploaded.</li>
      </ul>
    </Card>
  );
}
