import { useState } from "react";
import type { Company, Verdict } from "../../types/api";
import { fetchCompany } from "../../lib/http";

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
  const [company, setCompany] = useState<Company | null>(null);
  const [companyLoading, setCompanyLoading] = useState(false);
  const [companyError, setCompanyError] = useState<string | null>(null);

  const loadCompany = () => {
    if (company || companyLoading) return;
    setCompanyLoading(true);
    setCompanyError(null);
    void fetchCompany(verdict.company_id)
      .then(setCompany)
      .catch(() => setCompanyError("公司资料加载失败"))
      .finally(() => setCompanyLoading(false));
  };

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
        {verdict.revenue_exposure != null && (
          <>
            <div className="meter-label">
              <span>业务暴露度</span>
              <span>{Math.round(verdict.revenue_exposure * 100)}%</span>
            </div>
            <div className="meter-track">
              <div className="meter-fill" style={{ width: `${verdict.revenue_exposure * 100}%` }} />
            </div>
          </>
        )}
      </div>

      <ul className="verdict-reasons">
        {verdict.reasons.map((reason, i) => (
          <li key={i}>{reason}</li>
        ))}
      </ul>
      <details
        className="evidence-details"
        onToggle={(event) => event.currentTarget.open && loadCompany()}
      >
          <summary>公司资料与核验证据（{verdict.evidence.length}）</summary>
          {companyLoading && <p className="company-loading">公司资料加载中…</p>}
          {companyError && <p className="company-loading">{companyError}</p>}
          {company && (
            <dl className="company-facts">
              <div>
                <dt>所属行业</dt>
                <dd>{company.industries.join("、")}</dd>
              </div>
              <div>
                <dt>主要产品</dt>
                <dd>{company.products.join("、")}</dd>
              </div>
              <div>
                <dt>经营约束</dt>
                <dd>{company.capacity_constraint}</dd>
              </div>
            </dl>
          )}
          <div className="evidence-list">
            {verdict.evidence.map((item) => (
              <article className="evidence-item" key={item.id}>
                <div className="evidence-head">
                  {item.source_url ? (
                    <a href={item.source_url} target="_blank" rel="noreferrer">
                      {item.title}
                    </a>
                  ) : (
                    <span>{item.title}</span>
                  )}
                  <span>{item.year ?? "年份未知"}</span>
                </div>
                <p>{item.excerpt}</p>
                <p className="evidence-score">相关度 {Math.round(item.relevance * 100)}%</p>
              </article>
            ))}
          </div>
        </details>
    </article>
  );
}
