import type {
  IndustryReport,
  ReportDimension,
  ReportFrameworkTable,
  ReportLevel,
} from "../../types/api";

const LEVEL_LABEL: Record<ReportLevel, string> = {
  high: "高",
  medium: "中",
  low: "低",
};

function FrameworkTable({ table }: { table: ReportFrameworkTable }) {
  return (
    <div className="report-framework">
      <h3>{table.name}</h3>
      <table>
        <thead>
          <tr>
            <th>维度</th>
            <th>强度</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, index) => (
            <tr key={index}>
              <td>{row.factor}</td>
              <td>
                <span className={`level-${row.level}`}>
                  {LEVEL_LABEL[row.level]}
                </span>
              </td>
              <td>{row.statement}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DimensionCard({ dimension }: { dimension: ReportDimension }) {
  return (
    <article className="report-dimension">
      <h3>{dimension.name}</h3>
      <p>{dimension.summary}</p>
      {dimension.key_facts.length > 0 && (
        <ul>
          {dimension.key_facts.map((fact, index) => (
            <li key={index}>{fact}</li>
          ))}
        </ul>
      )}
      {dimension.sources.length > 0 && (
        <div className="report-source-links">
          {dimension.sources.map((source, index) =>
            source.startsWith("http") ? (
              <a key={index} href={source} target="_blank" rel="noreferrer">
                来源 {index + 1}
              </a>
            ) : (
              <span key={index}>{source}</span>
            )
          )}
        </div>
      )}
    </article>
  );
}

export default function ReportBlock({ report }: { report: IndustryReport }) {
  if (!report) return null;
  return (
    <section className="report-block">
      <div className="section-head">
        <h2 className="section-title">产业研究报告</h2>
        <span className="section-count">
          {report.generated_by === "llm" ? "LLM 生成" : "规则模板"}
          {report.model_name ? ` · ${report.model_name}` : ""}
        </span>
      </div>

      <div className="report-role-card">
        <span className="report-role-badge">{report.role.name}</span>
        <p className="report-role-perspective">{report.role.perspective}</p>
      </div>

      <p className="report-exec-summary">{report.executive_summary}</p>

      {report.dimensions.length > 0 && (
        <div className="report-dimension-grid">
          {report.dimensions.map((dimension) => (
            <DimensionCard key={dimension.key} dimension={dimension} />
          ))}
        </div>
      )}

      {[report.swot, report.porter_five_forces, report.pest]
        .filter((table): table is ReportFrameworkTable => Boolean(table))
        .map((table) => (
          <FrameworkTable key={table.name} table={table} />
        ))}

      {report.sources.length > 0 && (
        <details className="report-sources">
          <summary>数据来源（{report.sources.length}）</summary>
          <ul>
            {report.sources.map((source, index) => (
              <li key={index}>
                {source.url ? (
                  <a href={source.url} target="_blank" rel="noreferrer">
                    {source.label}
                  </a>
                ) : (
                  <span>{source.label}</span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
