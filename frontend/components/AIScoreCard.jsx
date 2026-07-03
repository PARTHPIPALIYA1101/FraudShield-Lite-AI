// Renders one fraud assessment in full (prop = FraudResult | FraudAssessment).

import { decisionColors, formatLatency, severityClasses } from "@/lib/format";

export function AIScoreCard({ result, compact = false }) {
  const colors = decisionColors(result.decision);
  const scorePct = Math.round(result.fraud_score * 100);

  return (
    <div className="space-y-4">
      {/* Score bar + decision/confidence */}
      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-xs font-medium uppercase tracking-wide text-white/50">
            Fraud Score
          </span>
          <span className={`text-sm font-semibold tabular-nums ${colors.text}`}>
            {result.fraud_score.toFixed(2)}
          </span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-white/10">
          <div
            className={`h-full rounded-full ${colors.dot}`}
            style={{ width: `${scorePct}%` }}
          />
        </div>
        <div className="mt-3 flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-wide text-white/40">
            AI rec
          </span>
          <span
            className={`rounded-md border px-2 py-0.5 text-xs font-semibold ${colors.bg} ${colors.border} ${colors.text}`}
          >
            {result.decision}
          </span>
          <span className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-xs text-white/60">
            {result.confidence} confidence
          </span>
        </div>
      </div>

      {/* Explanation */}
      {result.explanation && (
        <p className="text-sm leading-relaxed text-white/80">{result.explanation}</p>
      )}

      {/* Risk factors */}
      {result.risk_factors.length > 0 && (
        <div>
          <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-white/50">
            Risk Factors
          </div>
          <ul className="space-y-1.5">
            {result.risk_factors.map((rf, i) => (
              <li
                key={`${rf.factor}-${i}`}
                className="flex items-start gap-2 text-sm"
              >
                <span
                  className={`mt-0.5 shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${severityClasses(rf.severity)}`}
                >
                  {rf.severity}
                </span>
                <span className="text-white/80">
                  <span className="font-medium text-white/90">{rf.factor}</span>
                  {rf.detail ? ` — ${rf.detail}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Patterns matched */}
      {result.patterns_matched.length > 0 && (
        <div>
          <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-white/50">
            Patterns Matched
          </div>
          <div className="flex flex-wrap gap-1.5">
            {result.patterns_matched.map((p, i) => (
              <span
                key={`${p}-${i}`}
                className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-xs text-white/60"
              >
                {p}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Pipeline metadata — auditability */}
      {!compact && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-white/10 pt-3 text-xs text-white/40">
          <span>model: {result.ai_model_used}</span>
          {result.inference_ms != null && (
            <span>latency: {formatLatency(result.inference_ms)}</span>
          )}
          <span>
            cache:{" "}
            <span className={result.cache_hit ? "text-emerald-400" : "text-white/40"}>
              {result.cache_hit ? "hit" : "miss"}
            </span>
          </span>
        </div>
      )}
    </div>
  );
}
