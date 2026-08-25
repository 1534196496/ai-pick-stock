# 知衡

知衡是一款面向个人投资者的股票与基金资产管理工具。它把日常最常用的两件事做好：管理真实持仓，以及分组整理仍在观察的标的。

V2 正在独立开发，保留原有 Streamlit 代码和部署方式，不复用旧产品的信息架构。

## 第一期范围

- 账户注册、登录、退出和安全的会话管理。
- 通过多个投资账户管理 A 股与中国公募基金持仓，包括数量、成本和基金双录入口径。
- 管理股票与基金自选，支持多个分组、备注、移动，以及从自选加入持有。
- 展示持仓市值、盈亏、官方净值、可选盘中估算以及明确的数据业务时间。
- 为后续扩展其他市场、交易流水、收益分析和提醒能力保留稳定边界。

知衡不连接券商、不自动下单，也不提供收益承诺或个性化投资建议。

## 技术架构

- Web：React 19、TypeScript、Vite、React Router、TanStack Query。
- API：Python 3.12、FastAPI、Pydantic、SQLAlchemy、Alembic。
- 数据库：PostgreSQL 17。
- 运行方式：Nginx 静态站点、API、Worker 和 PostgreSQL 独立容器。

V2 采用模块化单体架构。账户、资产目录、持仓、自选和行情数据各自保持清晰边界，先控制运维复杂度，再按实际规模演进。

页面请求只读取本地 PostgreSQL；Worker 在后台同步用户持有或自选涉及的行情，第三方接口故障不会让页面请求同步卡住。详细边界见[总体设计](docs/dev-workflow/portfolio-watchlist-v2/04-设计方案.md)和[行情数据源决策](docs/architecture/adr/0001-market-data-sources.md)。

## 本地启动 V2

需要 Docker Engine 与 Docker Compose 插件。

```bash
cp .env.v2.example .env.v2
```

编辑 `.env.v2`，为 `POSTGRES_PASSWORD` 设置足够长的随机密码，并把同一个密码写入 `AIPICKSTOCK_DATABASE_URL`。然后启动：

```bash
V2_ENV_FILE=.env.v2 docker compose -f compose.v2.yaml up -d --build
docker compose -f compose.v2.yaml ps
```

默认地址：

- Web：`http://127.0.0.1:18080`
- API 存活检查：`http://127.0.0.1:18000/api/v1/health/live`
- API 就绪检查：`http://127.0.0.1:18000/api/v1/health/ready`

PostgreSQL 不映射宿主机端口。停止服务时不会删除数据库卷：

```bash
docker compose -f compose.v2.yaml down
```

默认示例关闭外部行情联网。需要实际同步资产目录和行情时，显式设置：

```dotenv
AIPICKSTOCK_MARKET_DATA_LIVE_ENABLED=true
```

基金盘中估算源在当前服务器不可达，因此默认关闭；官方单位净值仍可正常同步。公开部署还必须把 `AIPICKSTOCK_ENVIRONMENT` 设为 `production`，配置正确的 `AIPICKSTOCK_PUBLIC_WEB_URL` 和容器可达的 SMTP，否则就绪检查会拒绝接收正式流量。

## 本地开发

需要 Python 3.12、[uv](https://docs.astral.sh/uv/) 以及 Node.js 24。

```bash
make bootstrap
make lint
make typecheck
make test
make build
```

所有可用命令可通过 `make help` 查看。

## 旧版应用

旧版研究工具仍保留在仓库根目录，继续使用原有 `compose.yaml` 和 Streamlit 数据卷。V2 使用独立的 `compose.v2.yaml`、镜像、网络、端口和 PostgreSQL 卷，两套服务可以并行运行。

## 数据与投资风险

- 股票行情、基金净值和资产目录来自免费公开页面，可能延迟、缺失或因上游变更暂时不可用。
- 基金权威估值只使用官方单位净值及其真实净值日期；盘中估算会单独标识，且不进入组合权威汇总。
- 本项目不连接券商、不执行交易、不验证用户录入是否与券商账单一致。
- 页面结果仅用于个人记录，不构成投资建议、收益预测或交易依据。
