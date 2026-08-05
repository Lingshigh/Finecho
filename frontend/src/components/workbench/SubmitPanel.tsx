import { useState, type FormEvent } from "react";
import { useAnalysisContext } from "../../contexts/AnalysisContext";

const DEMO_POLICY = {
  title: "新型储能示范政策",
  text: "支持新型储能项目建设，推动储能电池、电池管理系统及新能源产业发展。",
};

export default function SubmitPanel() {
  const { phase, submit, error } = useAnalysisContext();
  const [title, setTitle] = useState(DEMO_POLICY.title);
  const [text, setText] = useState(DEMO_POLICY.text);
  const disabled = phase === "submitting" || phase === "running";

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (title.trim().length < 2 || text.trim().length < 20) return;
    await submit(title.trim(), text.trim());
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

        {error && <p className="submit-error">{error}</p>}

        <button type="submit" className="btn btn-primary" disabled={disabled}>
          {phase === "submitting" ? "提交中…" : phase === "running" ? "分析中…" : "开始分析"}
          <span className="arrow">→</span>
        </button>
      </form>
    </section>
  );
}
