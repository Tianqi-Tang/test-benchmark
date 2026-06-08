# test-benchmark 文档入口

本文档是 `docs/` 的导航页，只负责指路，不替代具体需求文档、backlog 或开发说明。

## 推荐阅读顺序

1. [协作指南](../AGENTS.md)
   - 项目定位、架构边界、开发顺序和不可随意改动的约束。
2. [开发说明](development.md)
   - 本地 Docker dev stack、端口、数据库和验证命令。
3. [Backlog](backlog.md)
   - 当前阶段、可延后事项和已知决策。
4. [需求分析流程](requirements/analysis-process.md)
   - 新增用户可见功能或跨模块变更前应遵循的轻量流程。
5. [医疗模型评测平台 MVP](requirements/evaluation-platform-mvp.md)
   - 第一版模型配置、题集导入、评测运行和结果展示需求。

## 文档区域

### 项目运行与交付

- [development.md](development.md) - 本地开发、Docker Compose、PostgreSQL 和验证说明。
- [deployment.md](deployment.md) - 测试环境部署和 nginx 路由约定。

### 需求与决策

- [requirements/analysis-process.md](requirements/analysis-process.md) - 需求分析流程。
- [requirements/templates/requirement-template.md](requirements/templates/requirement-template.md) - 需求文档模板。
- [requirements/evaluation-platform-mvp.md](requirements/evaluation-platform-mvp.md) - 第一版评测平台需求。

## 维护规则

- 新增用户可见功能或跨模块变更前，优先新增或更新 `requirements/` 下的需求文档。
- 已完成事项可以在需求文档中勾选验收标准，后续待办沉淀到 `backlog.md`。
- 原始题集资料不要直接改写成开发任务；先提炼到需求文档或 backlog。
- 文档索引用于降低查找成本，不应重复写完整需求细节。
