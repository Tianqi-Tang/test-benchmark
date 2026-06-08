# Backlog

## 当前阶段

项目已完成基础 Web 框架、Docker 本地开发脚本和 GitHub Actions 部署框架。下一阶段进入医疗模型评测平台第一版。

第一版目标详见：

- [医疗模型评测平台 MVP](requirements/evaluation-platform-mvp.md)

## P0

- [ ] PostgreSQL 接入本地和测试环境 Docker Compose。
- [ ] 后端建立模型配置、题集、题目、评测运行、评测结果表。
- [ ] 前端提供模型配置页面，支持 provider、model、baseUrl、apiKey、capability 配置。
- [ ] 支持导入 `data/benchmarks/custom_medical_eval_sets/*.jsonl`。
- [ ] 支持选择一个或多个模型，对一个题集发起评测。
- [ ] 支持评测运行进度和结果明细页面，评测过程中前端可实时刷新。
- [ ] 支持选择题直接评分。
- [ ] 支持问答题结果保存和第一版可解释评分规则。

## P1

- [ ] 支持手动结构化录入题目。
- [ ] 支持上传 JSONL 文件导入题集。
- [ ] 支持导出评测结果 CSV 或 JSON。
- [ ] 支持重新运行失败题目。
- [ ] 支持评测运行取消。
- [ ] 支持模型连通性测试。

## P2

- [ ] 支持 MedBench_LLM 更多题集格式。
- [ ] 支持 MedBench_Agent 题集。
- [ ] 支持 MedBench_VLM 多模态题集和图片导入。
- [ ] 支持图片资源清理策略和管理页面。
- [ ] 引入 LLM-as-judge 作为辅助评分，不替代标准答案直接评分。
- [ ] 支持 token、耗时、成本统计。

## 已确认决策

- 数据库使用 PostgreSQL。
- 第一版只支持 `custom_medical_eval_sets`。
- 第一版优先对有标准答案的题目直接评分。
- API key 只在服务端保存和使用，前端只展示脱敏值。
- 多模态图片后续导入到服务器管理目录，不能依赖原始本地数据路径。
- 本地访问使用 `http://localhost:18110/`，测试环境使用 `http://20.2.81.240/test-benchmark/`。
