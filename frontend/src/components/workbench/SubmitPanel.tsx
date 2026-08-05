import { useState, type FormEvent } from "react";
import { useAnalysisContext } from "../../contexts/AnalysisContext";

const DEMO_POLICY = {
  title: "新型储能示范政策",
  text: "支持新型储能项目建设，推动储能电池、电池管理系统及新能源产业发展。",
};

// 行业下拉选项，与 agent/nodes.py 的 INDUSTRY_HINT_OPTIONS 保持同步。
const INDUSTRY_OPTIONS = [
  "储能",
  "光伏",
  "新能源汽车",
  "人工智能",
  "半导体",
  "机器人",
  "低空经济",
  "数字经济",
  "生物医药",
  "氢能",
  "绿色低碳",
  "智能航运",
  "科技金融",
];

export default function SubmitPanel() {
  const { phase, submit, error } = useAnalysisContext();
  const [title, setTitle] = useState(DEMO_POLICY.title);
  const [text, setText] = useState(DEMO_POLICY.text);
  const [sourceUrl, setSourceUrl] = useState("");
  const [targetCompanies, setTargetCompanies] = useState("");
  const [maxDepth, setMaxDepth] = useState<1 | 2 | 3>(3);
  const [lenientMatching, setLenientMatching] = useState(false);
  const [industryHint, setIndustryHint] = useState("");
  const disabled = phase === "submitting" || phase === "running";

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (title.trim().length < 2 || text.trim().length < 20) return;
    const targets = targetCompanies
      .split(/[,;\n\uFF0C\uFF1B]/)
      .map((value) => value.trim())
      .filter(Boolean);
    await submit({
      policy_title: title.trim(),
      policy_text: text.trim(),
      source_url: sourceUrl.trim() || null,
      target_companies: targets,
      max_depth: maxDepth,
      lenient_matching: lenientMatching,
      industry_hint: industryHint || null,
    });
  };

  return (
    <section className="submit-panel">
      <h2 className="submit-title">输入政策，开始归因分析</h2>
      <p className="submit-sub">多 Agent 工作流将解构政策、沿产业链匹配上市公司，并做对抗式核验。</p>

      <form className="submit-form" onSubmit={onSubmit}>
        <label className="field">
          <span className="field-label">政策标题</span>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="例如：新型储能示范政策"
            maxLength={200}
            disabled={disabled}
          />
        </label>

        <label className="field">
          <span className="field-label">政策正文</span>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="粘贴政策原文或要点，至少 20 字……"
            rows={5}
            maxLength={100000}
            disabled={disabled}
          />
        </label>

        <details className="advanced-options">
          <summary>高级分析选项</summary>
          <div className="advanced-grid">
            <label className="field field-wide">
              <span className="field-label">政策来源链接（可选）</span>
              <input
                type="url"
                value={sourceUrl}
                onChange={(e) => setSourceUrl(e.target.value)}
                placeholder="https://..."
                disabled={disabled}
              />
            </label>

            <label className="field field-wide">
              <span className="field-label">指定核验公司（可选）</span>
              <input
                type="text"
                value={targetCompanies}
                onChange={(e) => setTargetCompanies(e.target.value)}
                placeholder="公司名称或代码，多个请用逗号分隔"
                disabled={disabled}
              />
              <span className="field-help">留空时由产业链自动匹配；指定后仅核验完全匹配的公司。</span>
            </label>

            <label className="field">
              <span className="field-label">政策类型/行业</span>
              <select
                value={industryHint}
                onChange={(e) => setIndustryHint(e.target.value)}
                disabled={disabled}
              >
                <option value="">自动识别（推荐）</option>
                {INDUSTRY_OPTIONS.map((industry) => (
                  <option key={industry} value={industry}>
                    {industry}
                  </option>
                ))}
              </select>
              <span className="field-help">指定后优先按该行业匹配公司，留空则从政策正文自动识别。</span>
            </label>

            <label className="field">
              <span className="field-label">图谱展示深度</span>
              <select
                value={maxDepth}
                onChange={(e) => setMaxDepth(Number(e.target.value) as 1 | 2 | 3)}
                disabled={disabled}
              >
                <option value={1}>1 · 政策与行业</option>
                <option value={2}>2 · 增加供应链</option>
                <option value={3}>3 · 完整展示到公司</option>
              </select>
            </label>

            <label className="check-field">
              <input
                type="checkbox"
                checked={lenientMatching}
                onChange={(e) => setLenientMatching(e.target.checked)}
                disabled={disabled}
              />
              <span>
                <strong>宽松匹配</strong>
                <small>扩大候选召回，适合较泛化的政策文本</small>
              </span>
            </label>
          </div>
        </details>

        {error && <p className="submit-error">{error}</p>}

        <button type="submit" className="btn btn-primary" disabled={disabled}>
          {phase === "submitting" ? "提交中…" : phase === "running" ? "分析中…" : "开始分析"}
          <span className="arrow">→</span>
        </button>
      </form>
    </section>
  );
}
