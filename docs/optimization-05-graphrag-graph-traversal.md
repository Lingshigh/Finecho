# FinEcho 优化记录 05：让 GraphRAG 名副其实——图遍历召回 + TF-IDF 证据排序

> 状态：已实现 · 关联优化：[01 多 Agent 条件路由](optimization-01-langgraph-multi-agent.md) · [03 核验评测基准](optimization-03-evaluation-benchmark.md)
> 日期：2026-08-04

## 一、问题描述

优化前 [rag_service.py](src/services/rag_service.py) **建了图但检索没用图**：

1. `_build_graph` 用 NetworkX 建了 `industry --contains--> company --produces--> product` 的关系图；
2. 但 `find_companies` 是**纯字符串 overlap**——逐家公司算查询词与公司行业/产品词的子串命中数；
3. `retrieve` 是**词袋交集**——算查询 token 与证据 token 的重叠个数。

"GraphRAG" 名不副实：图只是摆设，实际检索退化为规则词表匹配。`chroma_persist_dir` 配置项与 `rag` 可选依赖也从未接入。

## 二、为什么要用图遍历 + TF-IDF（方法选型理由）

### 1. 为什么候选召回用 BFS 图遍历，而非字符串 overlap

| 维度 | 字符串 overlap（原） | BFS 图遍历（新） |
|---|---|---|
| **语义结构** | 平等看待所有词，忽略行业/公司/产品的关系 | 沿 `industry → company → product` 传导路径扩展，体现产业链结构 |
| **传递性** | 只能匹配"查询词直接出现在公司标签里"，跨层关联（查行业命中其供应链公司）需靠子串碰运气 | 从查询词落图节点出发，`industry:储能 → 宁德时代` 一步可达，天然捕获跨层传导 |
| **排序依据** | 命中次数（词频），同权 | 图路径距离，越近越相关（dist=1 行业直达 > dist=2 经产品中转） |
| **噪音** | `"半导体"` 被 `"半导"` 子串误触发等 | 只从真实存在的图节点出发，杜绝"伪节点"误匹配 |

**关键点**：突发政策的核心是"传导"——政策利好某个行业，受益的是该行业供应链上的公司。BFS 沿图边扩展，正好把"行业 → 供应链 → 公司"的传导链编码进检索本身。字符串 overlap 无法表达"这个公司是这个行业的供应链上游"这类结构关系。

### 2. 为什么证据排序用 TF-IDF 余弦，而非词袋交集

| 维度 | 词袋交集（原） | TF-IDF 余弦（新） |
|---|---|---|
| **词权重** | 所有词等权，常见词（"公司""业务"）淹没关键词 | IDF 压低常见词、抬高判别词（"储能电池""问询函"） |
| **向量化** | 集合交集，无法衡量部分重叠的相似程度 | 文档与查询映射到 TF-IDF 向量空间，余弦度量语义相似度 |
| **可解释性** | relevance 是拍脑袋的 `0.45 + overlap*0.08` | 归一化的余弦相似度，0 表示无关、1 表示最相关 |
| **扩展性** | 换 Embedding 需要推翻重写 | 同一接口可平滑替换为稠密向量（见后续方向） |

**TF-IDF 比词袋强的核心**：词袋把"储能电池研发投入"和"储能电池出货规模"视为几乎无关（只有 1 个词重叠），但 TF-IDF 余弦会给两者合理的中等相似度，因为"储能电池"这一判别词的权重高。对证据相关性排序，区分度至关重要。

## 三、实现

### 1. 图遍历候选召回 `find_companies`

```python
def find_companies(self, industries, products, targets=None):
    start_nodes = self._resolve_start_nodes([*industries, *products])   # 查询词落图
    undirected = self.graph.to_undirected()                              # 双向遍历
    distances = {}
    for start in start_nodes:
        for node, dist in nx.single_source_shortest_path_length(undirected, start, cutoff=2).items():
            if self.graph.nodes[node].get("kind") == "company":
                distances[node] = min(distances.get(node, dist), dist)
    # 图距离越近分越高：dist=1（行业直达）满分，dist=2（经产品中转）0.6，再叠加收入暴露度
    return sorted(companies, key=lambda c: graph_score(c) + revenue_exposure, reverse=True)
```

- `_resolve_start_nodes` 把查询词映射到图中 `industry:X` / `product:X` 节点（精确 label 优先，子串兜底且**校验节点存在**）；
- BFS 用无向图，因为 `company → product` 是 `produces` 单向边，查询词从 product 出发需反向抵达 company；
- `cutoff=2` 限制扩展半径，避免全图漫游。

### 2. TF-IDF 证据排序 `retrieve`

```python
def _build_tfidf(self):
    # 统计文档频率 → IDF，为每篇证据文档建词频向量（L2 归一化）
    self._idf = {token: log(1 + N / (1 + df)) for token, df in doc_freq.items()}
    self._doc_vectors[doc_id] = self._vectorize(doc_text)

def retrieve(self, company_id, query, limit=3):
    qv = self._vectorize(query)
    ranked = [(self._cosine(qv, self._doc_vectors[doc_id]), doc)
              for doc in self.documents if doc["company_id"] == company_id]
    # 对命中集合按最大余弦做 min-max 归一化，使每家 top 证据相关度可比
```

**归一化的必要**：TF-IDF 稀疏向量的绝对余弦普遍偏低（0.05-0.3），直接喂给下游 `_evidence_sufficient` 的 0.4 阈值会误判"证据不足"。归一化后每家 top 证据为 1.0，阈值语义从"绝对相似度"变为"是否检索到任何命中"。

### 3. 连带改进：`route_evidence` 一次放宽

BFS 召回会纳入"自称涉足相关行业但无证据"的公司（如幻影科技），旧逻辑对这类候选会**无限放宽循环**（放大关键词也无济于事）。`route_evidence` 改为**最多放宽一次**：先尝试扩词，仍无证据则接受现实进入核验（判定"证据有限"）。既保留尽力检索语义，又不空转。

## 四、验证

### 单元测试 `tests/test_rag.py`

| 测试 | 断言 |
|---|---|
| `test_find_companies_uses_graph_traversal` | 光伏政策下通威/隆基进前三，演示公司被图路径排除 |
| `test_find_companies_graph_distance_ranks_near_first` | 储能查询 dist=1 直达宁德时代排第一 |
| `test_retrieve_uses_tfidf_cosine` | top 证据归一化 relevance==1.0，全在 [0,1] |
| `test_retrieve_empty_when_no_match` | 无匹配返回空，不虚构相关度 |

### 评测基线（16 例）

```
ACC 0.688（不变）  hotspot AUC 0.7（不变）
hotspot_risk: precision=1.000  recall=0.500
```

改造后核验判定与旧版一致——**图遍历与 TF-IDF 替换检索实现，但不劣化核验质量**，同时让"GraphRAG"名副其实。

### 测试与 lint

```
18 passed, 1 warning
ruff: All checks passed
```

## 五、影响与后续

### 影响

- 候选召回从词表匹配升级为**结构化的图传导检索**，能表达"行业 → 供应链 → 公司"的产业链语义；
- 证据排序从词袋交集升级为 **TF-IDF 余弦**，判别词权重合理、相似度可解释、可归一化；
- 连带修复了"无证据候选导致无限放宽循环"的空转问题。

### 后续方向

1. **升级为稠密向量**：`retrieve` 的 `_vectorize` 接口已隔离，可平滑替换为 `sentence-transformers` / ChromaDB 向量召回（`chroma_persist_dir` 配置已预留），TF-IDF 作为无模型 fallback；
2. **图数据库迁移**：`find_companies` 的 BFS 逻辑可平移至 Neo4j Cypher 查询，支持万级节点规模；
3. **传导权重学习**：当前 BFS 等权走边，后续可给 `contains`/`produces` 边加权（如营收占比），让排序更贴近真实受益强度。
