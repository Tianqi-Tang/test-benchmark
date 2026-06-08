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
- [x] 题目保存原始 JSON、题干、选项、标准答案和题型。
- [x] 评测运行页面，可选择一个题集和一个或多个模型。
- [x] 后端创建评测运行记录和逐题结果记录。
- [x] 后端逐题调用模型并保存回答、耗时、错误和评分结果。
- [x] 前端结果页展示运行状态、进度、准确率和逐题明细。
- [x] 前端通过轮询实现第一版实时更新。

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
| qwen3.7-plus | `qwen` | `qwen3.7-plus` | 文本 | OpenAI 兼容接口 |
| ChatGPT gpt-5.5 | `openai_responses` | `gpt-5.5` | 文本、多模态 | OpenAI 模型，后端通过 Responses API 调用 |
| Gemini 3.5 Flash | `gemini` | `gemini-3.5-flash` | 文本、多模态 | Google Gemini |

### 多模态模型

多模态模型配置字段先预留，第一版不执行 vision 题评测。

| 展示名称 | 内部 provider | 默认模型 | 支持能力 |
| --- | --- | --- | --- |
| qwen3.7-plus | `qwen_vision` | `qwen3.7-plus` | 文本、多模态 |
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

第一版问答题保留标准答案和模型输出。自动评分采用保守规则：

- 完全归一化一致：正确。
- 标准答案短文本且模型输出包含标准答案：正确。
- 其他情况：标记为待人工复核或错误。

问答题语义评分、LLM-as-judge 和人工评分流程放到后续版本。

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
- `correct_count`
- `accuracy`
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
- `GET /api/benchmark-sets/{id}/questions`
- `PUT /api/benchmark-questions/{id}`
- `DELETE /api/benchmark-questions/{id}`

### 评测

- `POST /api/evaluation-runs`
- `GET /api/evaluation-runs`
- `GET /api/evaluation-runs/{id}`
- `GET /api/evaluation-runs/{id}/results`
- `GET /api/dashboard/model-scores`，默认返回全部模型；未参与过评测的模型也要出现在看板中，并标记为未评测。

## 模型调用约束

- 后端直接调用模型 provider，不从前端发起模型请求。
- `apiKey` 不返回明文。
- provider 适配层参考已验证的内部 provider 形态：
  - `deepseek`、`qwen`、`qwen_vision` 可按 OpenAI 兼容 Chat Completions 处理。
  - `openai_responses` 使用 Responses API。
  - `gemini` 使用 Gemini HTTP API。
  - `ant_ling` 使用其 OpenAI 兼容或指定 HTTP 接口。
- 调用失败时记录错误，不中断整个评测运行。

## 文件存储约束

第一版不评测图片，但数据模型和部署目录要预留 vision 资产管理。

后续 vision 导入时：

- 图片复制到服务器 `storage/benchmark-assets/`。
- 路径按题集和导入批次分层。
- 数据库保存相对路径和原始来源路径。
- 删除题集或导入批次时，应能定位可清理目录。

## 前端页面

- 模型配置：列表、创建、编辑、启用/禁用、测试连接。
- 登录页：未登录用户只能看到登录页；登录成功后进入评测工作台，可主动退出登录。
- 题集管理：题集列表、手动上传 JSONL 导入题集、查看题目、编辑题目、删除题目。
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
- [x] S 场景：前端任何接口都不会返回 API key 明文。
- [ ] S 场景：测试环境访问模型配置、题集、评测和结果 API 前必须先登录，密码校验在后端完成。
- [x] S 场景：后端运行依赖 PostgreSQL，Docker 本地和测试环境均配置 PostgreSQL。

## 开放问题

- 问答题第一版是否需要人工复核页面，还是只保存结果供查看。
- 评测任务是否需要取消能力。
- 同一个题集导入后是否需要版本号。
- 是否需要为每次评测保存 prompt 模板版本。
- 多模型并发调用的默认并发数应是多少。
