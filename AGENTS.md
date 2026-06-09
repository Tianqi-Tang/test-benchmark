# test-benchmark Collaboration Guide

## 项目定位

`test-benchmark` 是医疗模型评测平台，用于对通用文本医疗模型和多模态医疗模型进行可配置、可复现、可查看明细的评测。

当前阶段的目标不是一次性覆盖所有医学 benchmark，而是先跑通第一版闭环：

- 在网页中配置模型。
- 将已有题集导入数据库。
- 选择模型和题集发起评测。
- 实时查看运行进度、汇总结果和逐题明细。
- 对有标准答案的题集直接评分。

## 架构边界

```text
Vue 3 Frontend :18110
    | /api
    v
Python FastAPI Backend :18111
    |
    v
PostgreSQL
    |
    +-- 模型配置、题集、题目、评测运行、评测结果
    +-- 服务器文件存储目录，保存上传或导入的图片资源
```

| Directory | Role | Constraint |
| --- | --- | --- |
| `frontend/` | Vue 3 管理界面 | 以配置、导入、运行、结果查看为主，不做营销页 |
| `backend/` | FastAPI API、模型调用、导入和评分逻辑 | API key 只在服务端保存和使用，不能返回给前端 |
| `data/benchmarks/` | 本地原始题集资料 | 不提交仓库，只作为导入来源 |
| `docs/` | 项目文档、需求和决策记录 | 新增用户可见功能前先补文档 |

## 第一版范围

第一版只支持 `data/benchmarks/custom_medical_eval_sets/` 下的文本题集：

- `dataset_upload_prod_医疗文本推理_0_59300178.jsonl`
- `dataset_upload_prod_医疗安全_0_59300178.jsonl`
- `dataset_upload_prod_医疗伦理_0_59300178.jsonl`

题型和评分：

- 选择题：根据模型输出抽取 `A-E` 选项，和标准答案精确匹配。
- 问答题：先保存模型输出和标准答案，第一版可做归一化精确/包含式评分；更复杂的语义评分后续单独设计。
- 不在第一版使用 LLM-as-judge 作为唯一评分依据。

## 模型配置原则

模型配置参考 HealthBot 已跑通的 provider 思路，但本项目不依赖 HealthBot 运行时，也不在产品文案中提及 HealthBot。

候选 provider 和模型包括：

- `ant_ling` / `AntAngelMed`
- `deepseek` / `DeepSeek-v4-pro`
- `qwen` / `qwen3.7-plus`
- `openai_responses` / `gpt-5.5`
- `gemini` / `Gemini-3.5-flash`

配置项至少包括：

- 展示名称
- provider
- model
- baseUrl
- apiKey
- capability: `text` 或 `vision`
- enabled
- maxOutputTokens

API key 规则：

- 只允许后端保存和读取。
- 前端列表和详情只展示脱敏值。
- 用户保存空 key 时不应覆盖已有 key，除非明确执行清空操作。

## 数据和文件存储

- 数据库使用 PostgreSQL，本地开发、测试环境和部署环境保持一致。
- 导入的题集进入数据库，原始 JSON 保留在题目记录中，便于追溯。
- Vision 图片后续导入时复制到服务器管理目录，不直接依赖原始 `data/benchmarks/` 路径。
- 图片存储目录应按题集和导入批次分层，便于清理，例如：

```text
storage/benchmark-assets/{benchmarkSetId}/{importBatchId}/...
```

- `storage/`、`data/`、评测输出和模型文件不得提交仓库。

## 开发顺序

涉及用户可见功能或跨模块变更时，先更新或新增 `docs/requirements/` 下的需求文档，再做实现。

推荐顺序：

1. 文档：确认目标、范围、数据模型、接口和验收标准。
2. 后端：数据库模型、导入、模型调用、评测任务和结果 API。
3. 前端：模型配置、题集导入、评测运行、结果页面。
4. 部署：Docker Compose、GitHub Actions、测试环境 nginx 路由。
5. 验证：后端测试、前端构建、本地 Docker stack。

## Frontend UI Rules

- 前端已使用 PrimeVue；新增或替换交互控件时优先使用 PrimeVue 组件，例如 `Button`、`Dialog`、`Select`、`Tag`、`Popover`，不要用原生 `button` 加临时样式凑合。
- 图标按钮使用 PrimeVue `Button` 的 `icon`、`text`、`rounded`、`severity`、`size` 等属性；不要手写孤立 icon button，除非已有组件无法满足。
- 短提示可以使用 PrimeVue Tooltip；题目、答案、记录、错误等长内容必须使用 Popover 或 Dialog，不能依赖浏览器原生 `title`。
- 列表页优先展示可扫描字段；长文本内容放到 Popover、Dialog 或详情页中查看。
- 新增弹窗和按钮时要和现有 PrimeVue 风格一致，操作按钮需要明确区分普通、警告和危险操作。

## 本地开发命令

```bash
bin/local-dev.sh start
bin/local-dev.sh status
bin/local-dev.sh logs
bin/local-dev.sh stop
```

默认本地地址：

- Web: `http://localhost:18110/`
- Backend health: `http://localhost:18111/health`

测试环境公网地址：

- `http://20.2.81.240/test-benchmark/`

## Git Workflow

- 使用 Conventional Commit：`<type>(<scope>): <subject>`。
- 不要在提交信息中添加 AI/tool 签名。
- 没有用户明确要求时，不创建 commit。
- 没有用户明确要求时，不 push。
- 用户确认“提交变更”后只提交；“推送代码”后再推送。
- `__pycache__`、`.pytest_cache`、前端缓存、构建缓存等已忽略的运行时文件不能影响提交判断；不要为了提交主动清理它们，也不要把它们纳入提交。

## Do Not Change Casually

- 本地 Web 端口 `18110`。
- 本地 Backend 端口 `18111`。
- 测试环境公网路径 `/test-benchmark/`。
- API key 的服务端保存和脱敏展示规则。
- 数据目录忽略规则：`data/`、`storage/`、评测输出、模型文件不提交。
- PostgreSQL 作为项目数据库的方向。
- 不要主动删除 `__pycache__` 或类似运行时缓存目录；除非用户明确要求，或它们确实造成测试、构建、运行失败。

## Reference Docs

- `docs/README.md` - 文档入口。
- `docs/development.md` - 本地开发和验证说明。
- `docs/backlog.md` - 待办和阶段记录。
- `docs/requirements/analysis-process.md` - 需求分析流程。
- `docs/requirements/evaluation-platform-mvp.md` - 第一版评测平台需求。
