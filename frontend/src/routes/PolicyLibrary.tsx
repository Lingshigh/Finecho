import { type FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import PolicyGraph from "../components/workbench/PolicyGraph";
import {
  analyzeCatalogPolicy,
  fetchPolicies,
  fetchPolicyAgentStatus,
  fetchPolicyLineage,
  fetchPolicyStats,
  importPolicyDocument,
  importPolicyHtml,
} from "../lib/http";
import type {
  AuthorityLevel,
  PolicyAgentAnalysisResponse,
  PolicyAgentStatus,
  PolicyDocument,
  PolicyDocumentImportPayload,
  PolicyImportResult,
  PolicyLineage,
  PolicyListResponse,
  PolicyStats,
} from "../types/api";

const LEVEL_LABEL: Record<string, string> = {
  central: "中央",
  state_council: "国务院",
  ministry: "部委",
  province: "省级",
  city: "市级",
  county: "区县",
  unknown: "待识别",
};

const TYPE_LABEL: Record<string, string> = {
  law: "法律",
  regulation: "条例",
  opinion: "意见",
  notice: "通知",
  plan: "规划/方案",
  measure: "办法",
  standard: "标准",
  announcement: "公告",
  interpretation: "政策解读",
  draft: "征求意见稿",
  news: "新闻",
  other: "其他",
};

const STATUS_LABEL: Record<string, string> = {
  draft: "征求意见",
  effective: "现行有效",
  amended: "已修订",
  repealed: "已废止",
  expired: "已失效",
  unknown: "待核验",
};

const AGENT_LABEL: Record<string, string> = {
  document_understanding: "政策文档识别",
  scope_extraction: "适用范围提取",
  impact_analysis: "政策影响分析",
  relation_reasoning: "政策关系推理",
};

function formatDate(value?: string | null): string {
  return value ? new Date(`${value}T00:00:00`).toLocaleDateString("zh-CN") : "待核验";
}

export default function PolicyLibrary() {
  const [catalog, setCatalog] = useState<PolicyListResponse | null>(null);
  const [stats, setStats] = useState<PolicyStats | null>(null);
  const [lineage, setLineage] = useState<PolicyLineage | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [level, setLevel] = useState("");
  const [industry, setIndustry] = useState("");
  const [documentType, setDocumentType] = useState("");
  const [loading, setLoading] = useState(true);
  const [lineageLoading, setLineageLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [importOpen, setImportOpen] = useState(false);
  const [documentImportOpen, setDocumentImportOpen] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [agentStatus, setAgentStatus] = useState<PolicyAgentStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchPolicies({
      q: query,
      authority_level: level,
      industry,
      document_type: documentType,
    })
      .then((result) => {
        if (cancelled) return;
        setCatalog(result);
        setSelectedId((current) => {
          if (current && result.items.some((item) => item.id === current)) return current;
          return result.items[0]?.id ?? null;
        });
      })
      .catch((reason: Error) => !cancelled && setError(reason.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [query, level, industry, documentType, reloadKey]);

  useEffect(() => {
    fetchPolicyStats().then(setStats).catch(() => undefined);
  }, [reloadKey]);

  useEffect(() => {
    fetchPolicyAgentStatus().then(setAgentStatus).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setLineage(null);
      return;
    }
    let cancelled = false;
    setLineageLoading(true);
    fetchPolicyLineage(selectedId)
      .then((result) => !cancelled && setLineage(result))
      .catch((reason: Error) => !cancelled && setError(reason.message))
      .finally(() => !cancelled && setLineageLoading(false));
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const selected = useMemo<PolicyDocument | null>(() => {
    return (
      lineage?.nodes.find((item) => item.id === selectedId) ??
      catalog?.items.find((item) => item.id === selectedId) ??
      null
    );
  }, [catalog, lineage, selectedId]);

  const industries = Object.entries(catalog?.facets.industries ?? {}).sort(
    (a, b) => b[1] - a[1]
  );

  const startAnalysis = async () => {
    if (!selected) return;
    setAnalyzing(true);
    setError(null);
    try {
      const task = await analyzeCatalogPolicy(selected.id);
      window.location.assign(`/workbench?task=${task.task_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "分析任务创建失败");
      setAnalyzing(false);
    }
  };

  return (
    <div className="policy-page">
      <header className="policy-header">
        <Link to="/" className="policy-brand">FinEcho</Link>
        <div className="policy-header-title">
          <strong>政策事实库</strong>
          <span>中央—部委—地方—产业影响</span>
        </div>
        <nav className="policy-header-actions">
          <button type="button" onClick={() => setImportOpen(true)}>导入 HTML</button>
          <button type="button" onClick={() => setDocumentImportOpen(true)}>导入正文</button>
          <Link to="/workbench">产业分析</Link>
        </nav>
      </header>

      <section className="policy-summary-bar">
        <div><span>政策记录</span><strong>{stats?.total ?? "—"}</strong></div>
        <div><span>正式文件</span><strong>{stats?.formal_documents ?? "—"}</strong></div>
        <div><span>中央依据</span><strong>{stats?.central_documents ?? "—"}</strong></div>
        <div><span>地方政策</span><strong>{stats?.local_documents ?? "—"}</strong></div>
        <div><span>待人工复核</span><strong>{stats?.pending_review ?? "—"}</strong></div>
        <div><span>AI Agent</span><strong className={agentStatus?.llm_configured ? "agent-online" : ""}>{agentStatus ? (agentStatus.llm_configured ? "模型增强" : "规则模式") : "…"}</strong></div>
        <p>影响结论均保留原文证据与置信度；索引样本不等同于已核验正文。</p>
      </section>

      {error && <div className="policy-global-error">{error}</div>}

      <main className="policy-workspace">
        <aside className="policy-filter-panel">
          <div className="policy-panel-heading">
            <strong>政策目录</strong>
            <span>{catalog?.total ?? 0} 份</span>
          </div>
          <label className="policy-filter-field">
            <span>搜索</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="政策、文号、机关或行业"
            />
          </label>
          <div className="policy-filter-grid">
            <label className="policy-filter-field">
              <span>发文层级</span>
              <select value={level} onChange={(event) => setLevel(event.target.value)}>
                <option value="">全部层级</option>
                {Object.entries(LEVEL_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
            <label className="policy-filter-field">
              <span>文件类型</span>
              <select value={documentType} onChange={(event) => setDocumentType(event.target.value)}>
                <option value="">全部类型</option>
                {Object.entries(TYPE_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="policy-industry-filter">
            <span>行业范围</span>
            <div>
              <button className={!industry ? "active" : ""} onClick={() => setIndustry("")}>
                全部
              </button>
              {industries.map(([name, count]) => (
                <button
                  key={name}
                  className={industry === name ? "active" : ""}
                  onClick={() => setIndustry(name)}
                >
                  {name}<small>{count}</small>
                </button>
              ))}
            </div>
          </div>
          <div className="policy-list" aria-busy={loading}>
            {loading && <p className="policy-list-empty">正在加载政策目录…</p>}
            {!loading && catalog?.items.length === 0 && (
              <p className="policy-list-empty">当前筛选下没有政策</p>
            )}
            {!loading && catalog?.items.map((policy) => (
              <button
                type="button"
                key={policy.id}
                className={`policy-list-item${selectedId === policy.id ? " active" : ""}`}
                onClick={() => setSelectedId(policy.id)}
              >
                <span className="policy-list-meta">
                  <i>{LEVEL_LABEL[policy.authority_level]}</i>
                  <time>{formatDate(policy.publish_date)}</time>
                </span>
                <strong>{policy.title}</strong>
                <span className="policy-list-tags">
                  <em>{TYPE_LABEL[policy.document_type]}</em>
                  <em>可信度 {policy.authenticity_grade}</em>
                </span>
              </button>
            ))}
          </div>
        </aside>

        <section className="policy-graph-panel">
          <div className="policy-panel-heading policy-graph-heading">
            <div>
              <strong>政策脉络</strong>
              <span>上下位依据、专项实施与地方细化关系</span>
            </div>
            <div className="policy-view-tabs">
              <button className="active">政策脉络</button>
              <button disabled>产业传导</button>
              <button disabled>企业验证</button>
            </div>
          </div>
          <PolicyGraph
            lineage={lineage}
            selectedId={selectedId}
            onSelect={setSelectedId}
            loading={lineageLoading}
          />
        </section>

        <aside className="policy-detail-panel">
          {selected ? (
            <>
              <div className="policy-detail-head">
                <span className={`policy-grade grade-${selected.authenticity_grade}`}>
                  可信度 {selected.authenticity_grade}
                </span>
                <h1>{selected.title}</h1>
                <p>{selected.summary}</p>
                <div className="policy-detail-actions">
                  <button type="button" onClick={startAnalysis} disabled={analyzing}>
                    {analyzing ? "正在创建…" : "进入产业影响分析"}
                  </button>
                  {selected.source_url && (
                    <a href={selected.source_url} target="_blank" rel="noreferrer">查看官方来源</a>
                  )}
                </div>
              </div>

              <dl className="policy-facts">
                <div><dt>发文机关</dt><dd>{selected.issuing_authorities.join("、") || "待核验"}</dd></div>
                <div><dt>政策层级</dt><dd>{LEVEL_LABEL[selected.authority_level]}</dd></div>
                <div><dt>文件类型</dt><dd>{TYPE_LABEL[selected.document_type]}</dd></div>
                <div><dt>效力状态</dt><dd>{STATUS_LABEL[selected.lifecycle_status]}</dd></div>
                <div><dt>发布日期</dt><dd>{formatDate(selected.publish_date)}</dd></div>
                <div><dt>文号</dt><dd>{selected.document_number || "待正文核验"}</dd></div>
              </dl>

              {selected.agent_runs.length > 0 && (
                <section className="policy-detail-section policy-agent-section">
                  <div className="policy-detail-title">
                    <h2>AI Agent 执行链</h2>
                    <span>规则护栏 · 结构化输出 · 证据校验</span>
                  </div>
                  <div className="policy-agent-pipeline">
                    {selected.agent_runs.map((run, index) => (
                      <article
                        className={`policy-agent-card agent-${run.status}`}
                        key={run.agent}
                      >
                        <div className="policy-agent-index">{index + 1}</div>
                        <div className="policy-agent-body">
                          <div>
                            <strong>{AGENT_LABEL[run.agent] ?? run.agent}</strong>
                            <em>{run.mode === "hybrid" ? "模型增强" : "规则执行"}</em>
                          </div>
                          <p>{run.summary}</p>
                          <span>
                            置信度 {Math.round(run.confidence * 100)}% · {run.evidence_count} 条证据
                          </span>
                          {run.warnings.map((warning) => (
                            <small key={warning}>{warning}</small>
                          ))}
                        </div>
                      </article>
                    ))}
                  </div>
                </section>
              )}

              <section className="policy-detail-section">
                <div className="policy-detail-title">
                  <h2>适用范围</h2>
                  <span>{Math.round(selected.scope.confidence * 100)}% 置信度</span>
                </div>
                <ScopeRow label="地域" values={selected.scope.regions} />
                <ScopeRow label="行业" values={selected.scope.industries} />
                <ScopeRow label="适用主体" values={selected.scope.target_entities} />
                <ScopeRow label="项目阶段" values={selected.scope.project_stages} />
                <ScopeRow label="准入条件" values={selected.scope.conditions} />
                <ScopeRow label="排除项" values={selected.scope.exclusions} />
                <div className="policy-scope-row">
                  <span>有效期</span>
                  <div>
                    {selected.scope.valid_from || selected.scope.valid_until ? (
                      <em>
                        {selected.scope.valid_from ? formatDate(selected.scope.valid_from) : "待核验"}
                        {" — "}
                        {selected.scope.valid_until ? formatDate(selected.scope.valid_until) : "待核验"}
                      </em>
                    ) : (
                      <small>待正文核验</small>
                    )}
                  </div>
                </div>
                {selected.scope.evidence[0] && (
                  <blockquote>{selected.scope.evidence[0].excerpt}</blockquote>
                )}
              </section>

              {selected.clauses.length > 0 && (
                <section className="policy-detail-section">
                  <div className="policy-detail-title">
                    <h2>正文条款</h2>
                    <span>{selected.clauses.length} 条 · 文档识别 Agent 拆分</span>
                  </div>
                  <ol className="policy-clause-list">
                    {selected.clauses.map((clause) => (
                      <li key={clause.id}>
                        {clause.heading && <strong>{clause.heading}</strong>}
                        <p>{clause.text}</p>
                      </li>
                    ))}
                  </ol>
                </section>
              )}

              <section className="policy-detail-section">
                <div className="policy-detail-title">
                  <h2>产业影响要点</h2>
                  <span>{selected.impacts.length} 项</span>
                </div>
                {selected.impacts.length ? selected.impacts.map((impact) => (
                  <article className="policy-impact-card" key={impact.id}>
                    <div>
                      <i className={`impact-${impact.direction}`} />
                      <strong>{impact.title}</strong>
                      <span>{Math.round(impact.confidence * 100)}%</span>
                    </div>
                    <p>{impact.summary}</p>
                    <div className="policy-chain-tags">
                      {impact.chain_nodes.map((node) => <em key={node}>{node}</em>)}
                    </div>
                    {impact.evidence[0] && <blockquote>{impact.evidence[0].excerpt}</blockquote>}
                  </article>
                )) : <p className="policy-section-empty">正文未接入，暂无可核验影响结论。</p>}
              </section>

              {selected.quality_warnings.length > 0 && (
                <section className="policy-quality-warning">
                  <strong>数据质量提示</strong>
                  {selected.quality_warnings.map((warning) => <p key={warning}>{warning}</p>)}
                </section>
              )}
            </>
          ) : (
            <div className="policy-detail-empty">从左侧选择一份政策查看适用范围与影响要点</div>
          )}
        </aside>
      </main>

      {importOpen && (
        <ImportDialog
          onClose={() => setImportOpen(false)}
          onImported={() => {
            setImportOpen(false);
            setReloadKey((value) => value + 1);
          }}
        />
      )}

      {documentImportOpen && (
        <DocumentImportDialog
          onClose={() => setDocumentImportOpen(false)}
          onImported={() => {
            setDocumentImportOpen(false);
            setReloadKey((value) => value + 1);
          }}
        />
      )}
    </div>
  );
}

function ScopeRow({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="policy-scope-row">
      <span>{label}</span>
      <div>{values.length ? values.map((value) => <em key={value}>{value}</em>) : <small>待正文核验</small>}</div>
    </div>
  );
}

function ImportDialog({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: (result: PolicyImportResult) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [sourceName, setSourceName] = useState("政策原文聚合中心");
  const [authorityName, setAuthorityName] = useState("");
  const [authorityLevel, setAuthorityLevel] = useState<AuthorityLevel>("ministry");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) {
      setError("请选择 HTML 文件");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await importPolicyHtml({
        source_name: sourceName,
        authority_name: authorityName,
        default_authority_level: authorityLevel,
        html: await file.text(),
      });
      onImported(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "导入失败");
      setSubmitting(false);
    }
  };

  return (
    <div className="policy-dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <form className="policy-import-dialog" onSubmit={submit} onMouseDown={(event) => event.stopPropagation()}>
        <div className="policy-dialog-head">
          <div><strong>导入政策 HTML</strong><span>自动隔离新闻、导航和截断标题</span></div>
          <button type="button" onClick={onClose} aria-label="关闭">×</button>
        </div>
        <label><span>HTML 文件</span><input type="file" accept=".html,.htm,text/html" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
        <label><span>来源名称</span><input value={sourceName} onChange={(event) => setSourceName(event.target.value)} required minLength={2} /></label>
        <label><span>发文机关</span><input value={authorityName} onChange={(event) => setAuthorityName(event.target.value)} placeholder="例如：国家能源局" required minLength={2} /></label>
        <label>
          <span>默认层级</span>
          <select value={authorityLevel} onChange={(event) => setAuthorityLevel(event.target.value as AuthorityLevel)}>
            {Object.entries(LEVEL_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <p className="policy-import-note">导入结果仅作为候选索引。正式文号、正文、适用范围和效力状态仍需详情页二次核验。</p>
        {error && <p className="policy-dialog-error">{error}</p>}
        <div className="policy-dialog-actions">
          <button type="button" onClick={onClose}>取消</button>
          <button type="submit" disabled={submitting}>{submitting ? "正在清洗…" : "导入并清洗"}</button>
        </div>
      </form>
    </div>
  );
}

function DocumentImportDialog({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: (result: PolicyAgentAnalysisResponse) => void;
}) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [sourceName, setSourceName] = useState("政策原文聚合中心");
  const [authorityName, setAuthorityName] = useState("");
  const [authorityLevel, setAuthorityLevel] = useState<AuthorityLevel>("ministry");
  const [persist, setPersist] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const payload: PolicyDocumentImportPayload = {
        title,
        content,
        source_name: sourceName,
        authority_name: authorityName,
        default_authority_level: authorityLevel,
        persist,
      };
      const result = await importPolicyDocument(payload);
      onImported(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "导入失败");
      setSubmitting(false);
    }
  };

  return (
    <div className="policy-dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <form className="policy-import-dialog" onSubmit={submit} onMouseDown={(event) => event.stopPropagation()}>
        <div className="policy-dialog-head">
          <div><strong>导入政策正文</strong><span>四 Agent 识别文档、提取范围、分析影响并推理关系</span></div>
          <button type="button" onClick={onClose} aria-label="关闭">×</button>
        </div>
        <label><span>政策标题</span><input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：关于支持储能产业发展的通知" required minLength={2} maxLength={300} /></label>
        <label><span>政策正文</span><textarea className="policy-document-textarea" value={content} onChange={(event) => setContent(event.target.value)} rows={10} placeholder="粘贴政策完整正文，包含文号、条款与适用范围…" required minLength={20} /></label>
        <label><span>来源名称</span><input value={sourceName} onChange={(event) => setSourceName(event.target.value)} required minLength={2} /></label>
        <label><span>发文机关</span><input value={authorityName} onChange={(event) => setAuthorityName(event.target.value)} placeholder="例如：国家能源局" required minLength={2} /></label>
        <label>
          <span>默认层级</span>
          <select value={authorityLevel} onChange={(event) => setAuthorityLevel(event.target.value as AuthorityLevel)}>
            {Object.entries(LEVEL_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="policy-document-persist">
          <span>写入政策库</span>
          <input type="checkbox" checked={persist} onChange={(event) => setPersist(event.target.checked)} />
          <small>勾选后结果入库并供目录查询；取消则仅预览不保存</small>
        </label>
        <p className="policy-import-note">Agent 结论默认为机器候选，所有范围、影响与关系均保留原文证据；证据无法复现时自动回退规则并记录 warning。</p>
        {error && <p className="policy-dialog-error">{error}</p>}
        <div className="policy-dialog-actions">
          <button type="button" onClick={onClose}>取消</button>
          <button type="submit" disabled={submitting || title.length < 2 || content.length < 20}>{submitting ? "Agent 分析中…" : "运行四 Agent 导入"}</button>
        </div>
      </form>
    </div>
  );
}
