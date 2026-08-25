# 行情样本维护说明

Provider 单元测试只使用 `apps/api/tests/fixtures/providers/` 中完全虚构的最小样本。更新流程：

1. 显式运行 `uv run python -m scripts.smoke_market_sources --live`，确认来源可达与结构摘要。
2. 不把真实完整响应写入仓库；只手工制作能覆盖字段边界的虚构最小 JSON。
3. 新样本不得包含真实用户、Cookie、令牌、完整请求头或持仓信息。
4. 正常、缺字段、错误类型、未知字段和非正财务值都必须有离线测试。
5. 第三方字段变化先更新 ADR 和适配器测试，再改变生产解析器。
