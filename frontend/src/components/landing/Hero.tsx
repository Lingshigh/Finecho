import { useState, type FormEvent } from "react";
import { useNavigate, Link } from "react-router-dom";
import HeroOrb from "./HeroOrb";

export default function Hero() {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim().length < 20) {
      setError("政策正文至少 20 字，粘贴一段政策要点即可。");
      return;
    }
    setError(null);
    navigate(`/workbench?q=${encodeURIComponent(text.trim())}`);
  };

  return (
    <section className="hero">
      <div className="container hero-inner">
        <div className="hero-copy">
          <h1 className="hero-title">
            FinEcho
            <span className="hero-title-dot">.</span>
          </h1>
          <p className="hero-subtitle">政策驱动的产业链归因与受益真实性核验</p>
          <p className="hero-desc">
            提交一条政策，多 Agent 工作流实时解构政策、沿产业链匹配上市公司，
            对抗式核验每家公司的受益真实性——高置信、关注、还是蹭热点。
          </p>

          <form className="hero-policy-form" onSubmit={onSubmit}>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="例如：支持新型储能项目建设，推动储能电池、电池管理系统及新能源产业发展……"
              rows={3}
            />
            {error && <p className="hero-policy-error">{error}</p>}
            <div className="hero-buttons">
              <button type="submit" className="btn btn-primary hero-btn">
                立即体验
                <span className="arrow">→</span>
              </button>
              <Link to="/workbench" className="btn btn-ghost">
                API 接入
                <span className="arrow">→</span>
              </Link>
              <Link to="/workbench" className="btn btn-ghost">
                Token Plan
              </Link>
            </div>
          </form>
        </div>

        <div className="hero-visual">
          <HeroOrb />
        </div>
      </div>
    </section>
  );
}
