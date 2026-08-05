const FEATURES = [
  {
    title: "实时进度",
    desc: "SSE 事件流推送 Agent 每一步：解构政策、扩展产业链、匹配公司、检索证据、对抗式核验，全程可视化。",
  },
  {
    title: "图谱归因",
    desc: "政策 → 行业 → 供应链 → 上市公司的传导路径以图谱呈现，哪家公司如何受益一目了然。",
  },
  {
    title: "对抗式核验",
    desc: "规则分 + LLM 立场加权合成，识别高置信受益标的与蹭热点概念风险，拒绝空谈。",
  },
];

export default function FeatureStrip() {
  return (
    <section id="features" className="feature-strip">
      <div className="container">
        <div className="feature-grid">
          {FEATURES.map((feature) => (
            <article key={feature.title} className="feature">
              <h3 className="feature-title">{feature.title}</h3>
              <p className="feature-desc">{feature.desc}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
