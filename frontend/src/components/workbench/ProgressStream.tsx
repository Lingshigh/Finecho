import { deriveSteps, overallProgress } from "../../lib/progress";
import { useAnalysisContext } from "../../contexts/AnalysisContext";

export default function ProgressStream() {
  const { phase, events } = useAnalysisContext();
  if (phase !== "running" && phase !== "complete") return null;

  const steps = deriveSteps(events);
  const { done, total } = overallProgress(events);
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <section className="progress-stream">
      <div className="progress-head">
        <span className="progress-label">Agent 执行进度</span>
        <span className="progress-count">
          {done}/{total || "?"}
        </span>
      </div>
      <div className="progress-track" role="progressbar" aria-valuenow={pct}>
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <ol className="steps">
        {steps.map((step) => (
          <li key={step.node} className={`step step-${step.status}`}>
            <span className="step-dot" aria-hidden="true" />
            <span className="step-name">{step.label}</span>
            {"attempt" in step && step.attempt > 1 && (
              <span className="step-attempt">×{step.attempt}</span>
            )}
            {step.status === "done" && <span className="step-check">✓</span>}
          </li>
        ))}
      </ol>
    </section>
  );
}
