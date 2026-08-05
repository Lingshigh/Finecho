import { useAnalysisContext } from "../../contexts/AnalysisContext";
import VerdictCard from "./VerdictCard";

export default function VerdictBoard() {
  const { phase, task, taskId } = useAnalysisContext();
  if (phase === "idle" || phase === "submitting") return null;

  if (phase === "failed") {
    return (
      <section className="verdict-board">
        <h2 className="section-title">核验结论</h2>
        <p className="graph-empty">分析失败，请检查政策文本后重试。</p>
      </section>
    );
  }

  const verdicts = task?.result?.verdicts;
  if (!verdicts || verdicts.length === 0) {
    return (
      <section className="verdict-board">
        <h2 className="section-title">核验结论</h2>
        <p className="graph-empty">未产生核验结论。</p>
      </section>
    );
  }

  return (
    <section className="verdict-board">
      <div className="section-head">
        <h2 className="section-title">核验结论</h2>
        <span className="section-count">{verdicts.length} 家公司</span>
      </div>
      <div className="verdict-grid">
        {verdicts.map((verdict) => (
          <VerdictCard key={verdict.company_id} verdict={verdict} taskId={taskId} />
        ))}
      </div>
    </section>
  );
}
