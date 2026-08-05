import type { Verdict } from "../../types/api";

const VERDICT_META: Record<
  Verdict["verdict"],
  { label: string; hint: string }
> = {
  high_confidence: { label: "高置信受益", hint: "业务与政策传导强相关" },
  watch: { label: "关注", hint: "相关性中等，需持续跟踪" },
  hotspot_risk: { label: "蹭热点风险", hint: "无实质业务，警惕炒作" },
};

export default function VerdictCard({ verdict }: { verdict: Verdict }) {
  const meta = VERDICT_META[verdict.verdict];
  const prob = Math.round(verdict.benefit_probability * 100);
  return (
    <article className={`verdict-card verdict-${verdict.verdict}`}>
      <header className="verdict-card-head">
        <div>
          <h3 className="verdict-name">{verdict.company_name}</h3>
          <span className="verdict-ticker">{verdict.ticker}</span>
        </div>
        <span className="verdict-badge">{meta.label}</span>
      </header>

      <p className="verdict-hint">{meta.hint}</p>

      <div className="verdict-meter">
        <div className="meter-label">
          <span>受益概率</span>
          <span>{prob}%</span>
        </div>
        <div className="meter-track">
          <div
            className="meter-fill"
            style={{ width: `${prob}%` }}
          />
        </div>
        <div className="meter-label">
          <span>背离度</span>
          <span>{Math.round(verdict.divergence_score * 100)}%</span>
        </div>
        <div className="meter-track">
          <div
            className="meter-fill meter-fill-dim"
            style={{ width: `${Math.round(verdict.divergence_score * 100)}%` }}
          />
        </div>
      </div>

      <ul className="verdict-reasons">
        {verdict.reasons.map((reason, i) => (
          <li key={i}>{reason}</li>
        ))}
      </ul>
    </article>
  );
}
