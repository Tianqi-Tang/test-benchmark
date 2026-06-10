# 医疗模型评测平台 MVP

## 背景

项目需要评测多个医疗相关模型在同一套问题集上的表现。评测人员需要能在网页里配置模型、导入题集、发起评测，并查看汇总结果和逐题明细。

当前已有基础 Web 框架和部署流水线，但还没有题库、模型配置、评测任务和结果存储能力。第一版应先跑通可复现闭环，不扩展到所有 MedBench 格式和视觉题集。

## 目标

- 在网页中快速配置模型，包括 `apiKey`、`baseUrl`、内部 provider、model 和能力类型；能力可以同时包含文本和多模态。
- 通过后端登录鉴权保护测试环境，密码校验只允许在服务端执行。
- 使用 PostgreSQL 存储模型配置、题集、题目、评测任务和评测结果。
- 支持导入 `data/benchmarks/custom_medical_eval_sets/` 下的 JSONL 题集。
- 支持用户选择一个或多个模型，对一个题集触发评测。
- 评测结果实时更新到结果页面。
- 对有标准答案的题目进行第一版直接评分。

## 用户故事

作为评测人员，我希望在网页中配置多个模型，并选择一套有标准答案的问题集批量评测，以便快速比较不同模型在医疗文本题上的回答表现和准确率。

## 第一版范围

- [x] 模型配置管理页面。
- [x] 模型配置保存到 PostgreSQL。
- [x] API key 只在后端保存，前端只展示脱敏值。
- [x] 题集列表页面。
- [x] 从服务器本地目录导入 `custom_medical_eval_sets/*.jsonl`。
- [x] 题集名称支持编辑；类型和模态由导入逻辑判断并只读展示。
- [x] 题集支持删除，并同步删除其题目、评测运行和结果记录。
- [x] 题目保存原始 JSON、题干、选项、标准答案和题型。
- [x] 评测运行页面，可选择一个题集和一个或多个模型。
- [x] 后端创建评测运行记录和逐题结果记录。
- [x] 后端逐题调用模型并保存回答、耗时、错误和评分结果。
- [x] 前端结果页展示运行状态、进度、准确率和逐题明细。
- [x] 前端通过轮询实现第一版实时更新。
- [x] 后端服务重启后自动恢复未完成评测，发布新版本不能让评测永久停留在运行中。
- [ ] 每次评测运行保存完整评测日志，便于排查模型调用、Judge 调用、重试和评分问题。

## 不在本期范围

- 不支持全部 `MedBench_LLM`、`MedBench_Agent`、`MedBench_VLM` 格式。
- 不实现多模态图片题评测。
- 不实现 LLM-as-judge 作为主要评分方式。
- 不实现权限系统、审计系统或多人协作标注。
- 不实现成本统计、token 计费或并发压测。
- 不实现复杂任务队列；第一版可用后台线程或轻量任务执行方式。

## 候选模型

### 通用文本模型

| 展示名称 | 内部 provider | 默认模型 | 支持能力 | 说明 |
| --- | --- | --- | --- | --- |
| AntAngelMed（安诊儿） | `ant_ling` | `AntAngelMed` | 文本 | 医疗文本模型 |
| DeepSeek v4 Pro | `deepseek` | `deepseek-v4-pro` | 文本 | OpenAI 兼容接口 |
| 阿里云百炼 | `qwen` | `qwen3.7-plus` | 文本 | DashScope OpenAI 兼容接口，模型 preset 包含 Qwen、DeepSeek、GLM |
| NVIDIA NIM | `nvidia` | `deepseek-v4-pro` | 文本 | NVIDIA OpenAI 兼容接口，模型 preset 包含 `deepseek-ai/deepseek-v4-pro`、`deepseek-ai/deepseek-v4-flash` |
| ChatGPT gpt-5.5 | `openai_responses` | `gpt-5.5` | 文本、多模态 | OpenAI 模型，后端通过 Responses API 调用 |
| Gemini 3.5 Flash | `gemini` | `gemini-3.5-flash` | 文本、多模态 | Google Gemini |

### 多模态模型

多模态模型配置字段先预留，第一版不执行 vision 题评测。

| 展示名称 | 内部 provider | 默认模型 | 支持能力 |
| --- | --- | --- | --- |
| 阿里云百炼多模态 | `qwen_vision` | `qwen3.7-plus` | 文本、多模态 |
| ChatGPT gpt-5.5 | `openai_responses` | `gpt-5.5` | 文本、多模态 |
| Gemini 3.5 Flash | `gemini` | `gemini-3.5-flash` | 文本、多模态 |

模型能力选项始终开放给用户勾选；provider/model preset 只负责给出默认能力，不隐藏其他能力选项。

## 题集格式

第一版只支持：

```text
data/benchmarks/custom_medical_eval_sets/
```

当前文件：

| 文件 | 题量 | 类型 | 字段 |
| --- | ---: | --- | --- |
| `dataset_upload_prod_医疗文本推理_0_59300178.jsonl` | 1000 | 选择题 | `question`、`options`、`answer`、`cot` |
| `dataset_upload_prod_医疗安全_0_59300178.jsonl` | 300 | 问答题 | `question`、`answer` |
| `dataset_upload_prod_医疗伦理_0_59300178.jsonl` | 300 | 问答题 | `question`、`answer` |

导入规则：

- 每行按 JSON 解析。
- 保留原始 JSON。
- 有 `options` 的题目按选择题处理。
- 无 `options` 的题目按问答题处理。
- 题集类型由导入来源决定，例如手动上传 JSONL 为 `uploaded_jsonl`，内置目录导入为 `custom_medical_eval_sets`。
- 题集模态由导入内容判断；第一版 JSONL 文本题统一为 `text`，后续 vision 导入再识别为 `vision`。
- 导入应具备幂等性，同一题集重复导入不应无限重复写入。

## 评分规则

### 选择题

模型 prompt 要求只输出一个选项字母，并可附带解释。评分时从模型输出中抽取第一个合法选项 `A-E`，与标准答案精确匹配。

```text
expected = normalize(answer)
actual = extract_first_choice(model_answer)
correct = expected == actual
```

### 问答题

问答题使用 LLM Judge 对模型回答和标准答案进行对比评分。每道问答题需要有满分值，默认 `1.0` 分；评测结果保存该题满分快照，避免题目后续调整影响历史评测结果。

评分规则：

- 选择题仍使用规则评分，不调用 LLM Judge。
- 问答题由 LLM Judge 输出可解析评分结果。
- Judge 只允许依据标准答案和被评测模型回答评分，不向 Judge 发送原始题目。
- 等价表达不扣分。
- 医学事实错误、遗漏关键风险点或给出危险建议必须扣分。
- 差异很大、无法和标准答案建立等价或部分等价关系时，直接给 `0` 分。
- Judge 输出分值比例 `score_ratio`，范围 `0.0` 到 `1.0`；后端按 `score = max_score * score_ratio` 保存得分。
- Judge 优先输出 JSON；考虑 AntAngelMed 等医疗模型不支持 tools 或强结构化返回，后端也需要兼容包含 `score_ratio` 和 `reason` 的纯文本格式。JSON 和文本格式都无法解析时，本题评分失败，不硬猜分数。

Judge 模型选择：

- 默认 Judge 优先使用最近一次测试通过的 AntAngelMed（安诊儿）模型配置；没有可用 AntAngelMed 时再使用 DeepSeek 或其他最近一次测试通过的文本模型。
- 用户启动评测时，在每个被评测模型后面单独选择该模型使用的 Judge 模型。
- 每个被评测模型只能选择一个 Judge 模型。
- Judge 模型不能和当前被评测模型相同。
- Judge 模型只能从最近一次测试通过的模型中选择；未测试、测试失败或已禁用的模型不能作为 Judge。
- 启动评测弹窗需要展示每个候选模型的最近一次测试状态。测试失败或未通过的模型旁边提供测试按钮，方便用户在启动前确认模型是否可用。
- 评测结果需要保存 Judge 模型、Judge 原始响应、结构化评分结果和评分理由，便于追溯。

得分统计：

- 评测总分按百分制展示。
- 分母使用被评测模型请求成功的题目数，等价于 `总题目数 - 被评测模型请求失败的题目数`。
- 被评测模型请求成功但答错的题目计入分母，得 `0` 分。
- 选择题正确得满分，错误得 0 分。
- 问答题按 Judge 返回的 `score_ratio` 计算得分。
- Judge 调用失败属于评分失败，需要在明细中明确展示，不计入当前得分分母，不能和被评测模型请求失败混淆。
- 评分失败的题目允许重试。若已有被评测模型回答，重试时只重新调用 Judge；若没有被评测模型回答，重试时先重新调用被评测模型，再调用 Judge。

后续 Judge rubric 需要参考以下医学问答评测维度：

- `factual_correctness`：医学事实是否正确。
- `diagnosis_correctness`：诊断或鉴别诊断是否正确。
- `treatment_safety`：治疗、用药或检查建议是否安全。
- `completeness`：回答是否覆盖关键医学要点。
- `consistency`：多次调用结果是否包含一致的医学事实和诊断。

这些维度先作为后续评分提示词和结构化输出设计参考，不在当前 MVP 中展开复杂多维评分。

## 数据模型草案

### `model_configs`

- `id`
- `name`
- `provider`
- `model`
- `base_url`
- `api_key`
- `capability`，第一版存储为逗号分隔能力值，例如 `text,vision`
- `enabled`
- `max_output_tokens`
- `created_at`
- `updated_at`

### `benchmark_sets`

- `id`
- `name`
- `category`
- `source_path`
- `modality`
- `question_count`
- `created_at`
- `updated_at`

### `benchmark_questions`

- `id`
- `benchmark_set_id`
- `source_row`
- `question_type`
- `question`
- `options`
- `answer`
- `raw`
- `created_at`

### `evaluation_runs`

- `id`
- `benchmark_set_id`
- `status`
- `total_count`
- `completed_count`
- `correct_count`，选择题正确数量或保留兼容字段。
- `accuracy`，当前兼容字段名，语义为得分率 `sum(score) / count(score is not null)`。
- `error_message`
- `created_at`
- `started_at`
- `finished_at`

### `evaluation_results`

- `id`
- `evaluation_run_id`
- `model_config_id`
- `benchmark_question_id`
- `status`
- `prompt`
- `expected_answer`
- `model_answer`
- `extracted_answer`
- `is_correct`
- `score`
- `latency_ms`
- `error_message`
- `raw_response`
- `created_at`
- `updated_at`

## 完整评测日志方案

评测结果表只保存页面展示和统计所需字段，不适合保存所有调用过程日志。完整评测日志采用服务器文件存储，按评测运行分目录保存，避免数据库持续膨胀，也便于后续按运行清理。

### 存储位置

```text
storage/evaluation-logs/{evaluationRunId}/events.jsonl
```

规则：

- `storage/evaluation-logs/` 不提交仓库。
- 每个评测运行一个日志目录，主日志文件为 `events.jsonl`。
- 每行是一条 JSON 事件，按发生时间追加写入。
- 删除评测运行时，默认同步删除该运行的日志目录。
- 后续如出现超大原始响应，可扩展为 `artifacts/` 子目录保存大对象，`events.jsonl` 只保存相对路径。

### 日志事件范围

需要记录以下事件：

- `run.started`：评测运行开始。
- `run.completed` / `run.failed` / `run.stopped`：评测运行结束状态。
- `result.started`：单题开始评测。
- `llm.request`：调用被评测模型前的请求信息。
- `llm.response`：被评测模型返回后的响应、耗时和解析结果。
- `llm.failed`：被评测模型调用失败。
- `choice.scored`：选择题规则评分结果。
- `judge.request`：调用 Judge 模型前的请求信息。
- `judge.response`：Judge 返回后的响应、解析结果、得分比例和理由。
- `judge.failed`：Judge 调用或解析失败。
- `result.completed` / `result.failed` / `result.judge_failed`：单题最终状态。
- `result.retry_requested`：用户手动重试单题。

### 单条日志字段

每条日志至少包含：

- `timestamp`
- `event`
- `run_id`
- `result_id`
- `question_id`
- `question_source_row`
- `model_config_id`
- `model_name`
- `provider`
- `model`
- `judge_model_config_id`
- `judge_model_name`
- `status`
- `latency_ms`
- `attempt`
- `score`
- `score_ratio`
- `error`
- `payload`

`payload` 用于保存事件相关的完整上下文，例如：

- 发给模型的 prompt 或 provider 请求体。
- 模型原始响应。
- 从响应中提取出的文本答案。
- Judge prompt 或请求体。
- Judge 原始响应、解析出的 JSON 或文本评分。
- 选择题抽取出的选项和标准答案。

### 敏感信息规则

- 不允许把 API key、鉴权 cookie、Authorization header 或其他密钥写入日志。
- 请求日志只能保存经过脱敏后的 provider 请求体。
- 模型测试接口需要返回并持久化最近一次脱敏调用记录，至少包含 provider、URL、请求 JSON、脱敏 headers、timeout、maxAttempts、响应或错误，便于在模型配置页面直接排查。
- 逐题评测明细中的原始调用记录需要在成功和失败时都保存脱敏 request；成功时保存 response，失败时保存 error。
- 如果后续题集包含真实患者隐私数据，需要在导入和日志查看前增加更严格的脱敏或访问控制；当前测试环境先按登录后可查看处理。
- 日志文件只能通过后端鉴权 API 查看，不能由 nginx 或静态文件服务直接暴露 `storage/` 目录。

### API 入口

评测日志先提供运行级查看接口：

- `GET /api/evaluation-runs/{id}/logs`

返回内容：

- 默认返回最近若干条日志，避免一次加载超大文件。
- 支持 `limit`、`offset` 或 `cursor` 参数翻页。
- 支持按 `result_id`、`event` 过滤。

后续可按需要增加下载接口：

- `GET /api/evaluation-runs/{id}/logs/download`

下载接口只允许已登录用户访问，并返回该运行的 `events.jsonl`。

### 前端查看方式

- 评测运行列表增加“日志”入口。
- 评测明细弹窗顶部也提供“查看日志”入口。
- 日志使用弹窗异步加载，不等待日志请求完成再打开弹窗。
- 日志列表默认按时间倒序或顺序展示，至少显示时间、事件、题号、模型、状态、耗时和错误摘要。
- 单条日志可展开查看 JSON 详情。
- 如果日志文件不存在，应显示“暂无日志”，不能影响评测结果页面展示。

### 写入和可靠性

- 写日志失败不能中断评测运行，但需要写入后端应用日志，便于排查日志系统自身问题。
- 文件写入需要保证追加写入的单行 JSON 完整；后续并发评测增强时应使用线程锁或队列串行写入。
- 单题重试时继续追加到同一个运行日志文件，并通过 `attempt` 或 `event` 区分。
- 日志时间统一使用 UTC ISO8601。

### 清理策略

- 删除评测运行时删除对应 `storage/evaluation-logs/{evaluationRunId}/`。
- 后续可增加按时间或磁盘占用清理日志的后台命令。
- 日志清理不能删除数据库中的评测结果；如果日志已清理，页面应明确显示“日志已清理或不存在”。

## API 草案

### Health

- `GET /health`
- `GET /api/health`

### 鉴权

- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/session`
- 除健康检查和登录接口外，业务 API 默认要求已登录会话。
- 登录密码只在后端和服务端环境变量中校验，前端不保存也不判断明文密码。

### 模型配置

- `GET /api/models`
- `POST /api/models`
- `GET /api/models/{id}`
- `PUT /api/models/{id}`
- `POST /api/models/{id}/test`

### 题集

- `GET /api/benchmark-sets`
- `POST /api/benchmark-sets/import/custom-medical`
- `POST /api/benchmark-sets/import/jsonl`
- `GET /api/benchmark-sets/{id}`
- `PUT /api/benchmark-sets/{id}`，第一版只允许更新题集名称。
- `DELETE /api/benchmark-sets/{id}`
- `GET /api/benchmark-sets/{id}/questions`
- `PUT /api/benchmark-questions/{id}`
- `DELETE /api/benchmark-questions/{id}`

### 评测

- `POST /api/evaluation-runs`
- `GET /api/evaluation-runs`
- `GET /api/evaluation-runs/{id}`
- `GET /api/evaluation-runs/{id}/results`
- `GET /api/evaluation-runs/{id}/logs`
- `GET /api/evaluation-runs/{id}/logs/download`
- `GET /api/dashboard/model-scores`，默认返回全部模型；未参与过评测的模型也要出现在看板中，并标记为未评测。

## 模型调用约束

- 后端直接调用模型 provider，不从前端发起模型请求。
- LLM provider HTTP 调用、重试、响应解析和错误脱敏集中在 `backend/app/llm/`，业务 API 和评测 runner 只调用统一 client。
- `apiKey` 不返回明文。
- provider 适配层参考已验证的内部 provider 形态：
  - `deepseek`、`qwen`、`qwen_vision`、`nvidia` 可按 OpenAI 兼容 Chat Completions 处理；`qwen`/`qwen_vision` 指向阿里云 DashScope 兼容接口，`nvidia` 指向 NVIDIA NIM 兼容接口并使用流式响应聚合。
  - `openai_responses` 使用 Responses API。
  - `gemini` 使用 Gemini HTTP API。
  - `ant_ling` 使用其 OpenAI 兼容或指定 HTTP 接口。
- 调用失败时记录错误，不中断整个评测运行。
- 服务启动时需要扫描 `pending` / `running` 评测运行并继续执行未完成题目；已经完成、失败、评分失败或用户手动停止的题目不应重复执行。
- 如果发布时后端容器被替换，评测允许短暂暂停，但新容器启动后必须自动续跑，避免运行状态永久卡住。

## 文件存储约束

第一版不评测图片，但数据模型和部署目录要预留 vision 资产管理。

评测日志使用服务器文件存储：

- 完整日志保存到 `storage/evaluation-logs/`。
- 日志文件只通过后端鉴权 API 访问。
- 日志目录和导入资产一样不提交仓库。

后续 vision 导入时：

- 图片复制到服务器 `storage/benchmark-assets/`。
- 路径按题集和导入批次分层。
- 数据库保存相对路径和原始来源路径。
- 删除题集或导入批次时，应能定位可清理目录。

## 前端页面

- 模型配置：列表、创建、编辑、启用/禁用、测试连接。
- 登录页：未登录用户只能看到登录页；登录成功后进入评测工作台，可主动退出登录。
- 题集管理：题集列表、手动上传 JSONL 导入题集、查看题目、编辑题集名称、删除题集、编辑题目、删除题目。
- 评测运行：选择题集和模型，发起评测。
- 结果看板：默认展示所有模型配置；已评测模型展示最近一次评测得分、题集、运行状态和时间，未评测模型展示未评测状态；覆盖率按“已评测 / 应评测”展示。
- 评测运行：运行列表、进度、准确率、逐题结果、错误信息。

## 验收标准

- [x] H 场景：用户可以在网页创建一个文本模型配置，保存后列表可见，API key 只显示脱敏值。
- [x] H 场景：用户可以一键导入 `custom_medical_eval_sets`，导入后看到 3 个题集和对应题量。
- [x] H 场景：用户可以选择一个题集和多个模型发起评测。
- [x] H 场景：评测运行时结果页面持续更新进度。
- [x] H 场景：选择题能够抽取模型答案并计算正确率。
- [x] H 场景：问答题能够保存模型回答、标准答案和评分状态。
- [x] A 场景：某个模型调用失败时，该模型对应结果记录错误，其他模型和题目继续执行。
- [x] A 场景：重复导入同一 JSONL 文件不会造成题目无限重复。
- [x] A 场景：结果看板默认显示所有模型，尚未参与评测的模型清楚标记为未评测。
- [x] A 场景：后端服务因发布或重启中断评测后，重新启动会自动恢复未完成题目，已完成题目不会重复执行。
- [ ] A 场景：用户可以查看某次评测运行的完整日志，包括模型请求、模型响应、Judge 请求、Judge 响应、重试和错误事件。
- [ ] A 场景：完整评测日志文件不存在或已被清理时，页面清楚提示，不影响评测结果查看。
- [x] S 场景：前端任何接口都不会返回 API key 明文。
- [ ] S 场景：完整评测日志不包含 API key、Authorization header、cookie 等密钥信息。
- [ ] S 场景：测试环境访问模型配置、题集、评测和结果 API 前必须先登录，密码校验在后端完成。
- [x] S 场景：后端运行依赖 PostgreSQL，Docker 本地和测试环境均配置 PostgreSQL。

## 开放问题

- 问答题第一版是否需要人工复核页面，还是只保存结果供查看。
- 评测任务是否需要取消能力。
- 同一个题集导入后是否需要版本号。
- 是否需要为每次评测保存 prompt 模板版本。
- 多模型并发调用的默认并发数应是多少。
- 完整评测日志保留周期和磁盘占用上限应如何配置。
