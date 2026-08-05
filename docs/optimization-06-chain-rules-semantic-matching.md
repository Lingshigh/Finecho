# FinEcho 优化记录 06：产业链规则表外置 + 语义化匹配

> 状态：已实现 · 关联优化：[03 核验评测基准](optimization-03-evaluation-benchmark.md) · [05 GraphRAG 图遍历](optimization-05-graphrag-graph-traversal.md)
> 日期：2026-08-04

## 一、问题描述

优化前 [nodes.py](agent/nodes.py) 的 `CHAIN_RULES` 存在两个问题：

1. **规则表硬编码在代码里**，只有光伏/储能/新能源车/AI/半导体/机器人 6 个行业。新增行业必须改代码、重发布，无法运营侧扩充；其他政策只能靠正则从标题抓 2-8 字关键词兜底，产生大量噪音关键词。
2. **匹配逻辑是子串互含** `rule_key in keyword or keyword in rule_key`，导致：
   - `"半导"` 误触发 `"半导体"` 规则；
   - `"储能电池"` 无法触发 `"储能"` 规则（子串方向相反时要碰运气）；
   - 同义词（"芯片"↔"半导体"、"电池"↔"储能"）完全不支持。

## 二、设计：规则外置 + 语义化匹配

### 1. 规则表外置 `data/chain_rules.json`

```
rules: [
  {
    "id": "semiconductor",
    "name": "半导体",
    "keywords": ["半导体", "芯片", "集成电路", "晶圆"],   ← 触发词（含同义词/别名）
    "industries": ["半导体", "电子"],                     ← 命中后产出的一级行业
    "products": ["材料", "设备", "芯片设计", "晶圆制造", "封装测试"]  ← 二级供应链节点
  }
]
```

- **数据与代码解耦**：新增行业只需在 JSON 追加条目，无需改代码；运营/研究员可自行扩充；
- **规则自治**：每条规则自带触发词、行业、供应链节点三要素，语义自包含。

### 2. 语义化匹配（完整词 + 同义词）

```
match_chain_rules(keywords, rules):
    for keyword in keywords:
        normalized = keyword.lower().strip()
        for rule in rules:
            if normalized in rule.keywords:    # 完整词比对（同义词在 keywords 里显式声明）
                → 产出 rule.industries + rule.products
```

- **完整词匹配**：`normalized in {k.lower() for k in rule.keywords}` 精确比对，不做 `in` 子串互含 → `"半导"` 不再误触发 `"半导体"`；
- **同义词展开**：别名作为独立触发词写入 `keywords`（`"芯片"`、`"集成电路"` 等），命中即触发对应规则 → 无需词向量模型即可覆盖常见别名；
- **规范化**：`lower().strip()` 统一大小写与首尾空白，避免 "AI" 与 "ai" 失配。

### 为什么不用词向量/LLM 做主匹配

同义词表是**零依赖、零延迟、完全可解释**的方案——运营者一眼能看出 `"芯片"` 为什么触发半导体。词向量（如 word2vec/Embedding 相似度）需要：
- 额外模型依赖与计算开销（每请求跑相似度）；
- 阈值调参（相似度多高算命中？），易产生"半导→半导体"这类过度泛化；
- 结果不可解释，评审追问"为什么这个政策命中半导体"时难以回答。

**边界清晰**：确定性同义词表管"已知别名"，LLM 提取（`extract_policy` 已有）管"未知政策的语义理解"。词向量留作未来需要处理海量动态政策时的升级路径。

## 三、实现

### 1. `data/chain_rules.json`

6 条规则全部外置，每条补充了 3-5 个同义词触发词（如光伏的 `"太阳能"`、储能的 `"钠离子电池"`、半导体的 `"芯片"`、AI 的 `"大模型"`）。

### 2. `agent/nodes.py`

```python
def load_chain_rules(data_dir: Path) -> dict[str, dict]:
    """从 data/chain_rules.json 加载规则表；文件缺失时返回空表（仅靠正则兜底）。"""
    ...

def match_chain_rules(keywords, rules) -> tuple[list[str], list[str]]:
    """完整词匹配 + 同义词展开；规范化后与规则触发词比对，不做子串互含。"""
    ...

# build_nodes 内：
chain_rules = load_chain_rules(rag.data_dir)   # 从数据目录加载，可扩充
```

- `expand_chain` 改用 `match_chain_rules` 匹配；
- `extract_policy` 的 fallback 改用规则触发词（含同义词）做全文匹配，替代原 `CHAIN_RULES`；
- 删除硬编码 `CHAIN_RULES`。

### 3. `RELATED_INDUSTRY_RULES` 同步更新

原映射以"新能源→政策相关产业"为键，现规则以 `name` 为键（`光伏→新能源`、`储能→新能源`），与 `broaden_match` 的行业泛化逻辑兼容。

## 四、验证

### 语义匹配实测

| 输入关键词 | 触发规则 | 说明 |
|---|---|---|
| `半导体` | 半导体 | 完整词命中 |
| `半导` | **无** | 子串不再误触发 ✅ |
| `电池` | 储能 | 同义词命中 |
| `芯片` | 半导体 | 同义词命中 |
| `量子计算` | 无 | 无关词不产生噪音 |

### 单元测试 `tests/test_agent.py`

| 测试 | 断言 |
|---|---|
| `test_chain_rules_load_from_json` | 规则从 JSON 加载、6 条齐全、每条含三要素 |
| `test_chain_rule_full_word_match_not_substring` | `"半导"` 不触发半导体，`"半导体"` 正常触发 |
| `test_chain_rule_synonym_matching` | `"电池"`→储能、`"芯片"`→半导体，无关词不命中 |

### 评测基线（16 例）

```
ACC 0.688（不变）  hotspot AUC 0.7（不变）
```

语义化匹配替代子串互含后，核验判定与旧版一致——修复误触发的同时不劣化识别质量。

### 测试与 lint

```
21 passed, 1 warning
ruff: All checks passed
```

## 五、影响与后续

### 影响

- 规则表从代码搬入 `data/chain_rules.json`，**新增行业零代码改动**；
- 子串误触发（`半导`→半导体）根除，同义词（芯片/电池）被显式覆盖；
- `expand_chain` / `extract_policy` fallback 统一走规则表，删除硬编码。

### 后续方向

1. **词向量升级**：当规则表膨胀到几十个行业、别名难以穷举时，可在 `match_chain_rules` 前加 Embedding 相似度作为候选召回，同义词表保底；
2. **运营侧编辑**：把 `chain_rules.json` 开放为 API（GET/POST），研究团队可自助扩充行业而不依赖发版；
3. **规则命中追溯**：在 `policy_summary` 或 `warnings` 里输出"命中了哪些规则/同义词"，供前端展示政策解构过程。
