# 知衡 · 全球多资产个人投资研究台

联网研究全球主要股市、全球证券、国内基金与全球 ETF、国债收益率、债券 ETF、黄金与商品，并在本地保存 A 股筛选、自选资产、真实持仓、研究笔记和重要事件。它不连接券商、不自动下单，也不承诺收益。

## 能做什么

- 以“拉取信息 → 分析 → 推荐 → 诊股/诊基”为核心流程；推荐中心可按日期、批次、股票行业和基金类别回看。
- 每天冻结数据源覆盖的全部沪深北 A 股快照（当前实测 5,543 只）、全部基金主数据（当前实测 27,522 份额）及六类境内公募基金绩效快照（当前实测 20,128 条），先入库，再做推荐资格过滤。
- 股票按行业、基金按产品类别独立分析，每个板块最多发布 5 只研究候选；不足 5 只明确留空，部分失败批次不发布。
- 股票分类保留源端原始行业并版本化，仅将能明确识别的行业归入宏观组；当前 73 个行业组，“综合”分组为 0。每个推荐批次保存模型参数、输入哈希、代码哈希和逐项预筛排除原因。
- 诊股/诊基展示总览、推荐轨迹和走势。股票含 MA20/60/120、MACD、RSI、布林带、ATR、成交量与回撤；基金含累计净值、滚动波动、回撤、Sharpe/Sortino 等。
- 从全 A 实时快照中筛出成交活跃的候选池，排除 ST/退市风险及低流动性标的。
- 在 34 只跨地区、跨行业的透明全球研究池中，以绝对质量门槛和行业/地区中性排序筛选候选；缺失必要指标即不入榜。
- 增量保存前复权日线、成交量、成交额和当日估值快照到 `data/stocks.db`。
- 按趋势 35%、风险 25%、估值 20%、流动性 10%、走势稳定性 10% 横截面评分。
- 提供按功能分菜单的个人网站：全局搜索、今日总览、股票/基金/债券/商品研究、交易账本、持仓、目标配置、风险、事件和数据状态。
- 收录美联储官方 FOMC 会议及会议纪要日期，并支持自定义事件和本机提前提醒。
- 查看全球主要指数；用 Yahoo 市场代码研究美股、港股、日股、欧洲股票、ETF、指数和商品连续合约。
- “半导体多空战况”按 15 秒轮询纳斯达克 SK海力士 ADR（`SKHY`）、美光（`MU`）、闪迪（`SNDK`）和费城半导体指数（`^SOX`）的一分钟行情，展示 VWAP、EMA、MACD、RSI、量能脉冲、量价压力及可解释多空分。
- 独立“市场雷达”菜单按大盘、板块、基金/个股和自定义四个粒度下钻，支持中国大陆、美国、日本、欧洲标签切换与一分钟实时涨跌对比。全球板块资金方向统一明确标注为“最近30分钟量价成交额代理”，不伪称交易所真实净流入。
- 从美国财政部官方数据读取国债收益率曲线，单独比较债券 ETF。
- 录入真实持仓，根据最新真实价格和汇率计算人民币估值、资产/币种暴露与集中度；任一数据缺失时拒绝合计。
- 交易账本按账户与成交币种分账，保留成交日汇率、人民币平均成本、已实现损益和分红，并与持仓数量对账。
- 所有页面显示数据来源和截止日期；联网失败时显示失败，不生成替代数字。

## 市场代码示例

- 美股：`AAPL`；港股：`0700.HK`；A 股全球代码：`600519.SS` / `000001.SZ`
- 日股：`7203.T`；德国股票：`SAP.DE`；英国股票：`SHEL.L`
- 指数：`^GSPC`；全球 ETF：`VT`；债券 ETF：`TLT`
- 黄金期货连续合约代理：`GC=F`。它不是现货黄金或实物金价格，存在期货换月影响。
- 可选调用 OpenAI Responses API 对量化清单做基于证据的二次审阅。
- 通过 Windows 任务计划程序在工作日收盘后自动运行。

## 安装与首次运行

需要 Python 3.11+。在 PowerShell 中执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -U pip
.\.venv\Scripts\python -m pip install -r requirements.lock
.\.venv\Scripts\python -m pip install -e "." --no-deps
.\.venv\Scripts\stock-picker.exe daily
```

首次运行要为股票池逐只下载历史数据，通常会比后续增量运行慢。若任一代码同步失败，任务会记录为 `partial`、返回非零状态并拒绝生成新的正式候选；下次运行会自动补齐。

启动个人网站：

```powershell
.\scripts\start_website.ps1
```

浏览器访问 `http://localhost:8501`。网站只监听本机；如需手机或外网访问，应先增加登录验证和 HTTPS，不建议直接开放端口。

## Docker Compose 服务器部署

服务器需要安装 Docker Engine 和 Docker Compose 插件。拉取代码后执行：

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

默认只绑定服务器的 `127.0.0.1:8501`，容器内部监听 `0.0.0.0:8501`。生产环境建议让 Nginx/Caddy 反向代理到 `http://127.0.0.1:8501`，并在代理层配置 HTTPS、登录认证和访问限制。查看运行状态与日志：

```bash
curl --fail http://127.0.0.1:8501/_stcore/health
docker compose logs -f dashboard
```

如确认服务器防火墙和访问控制已经配置好，也可在 `.env` 中设置 `BIND_ADDRESS=0.0.0.0` 后重启，使 `http://服务器IP:8501` 可访问。该应用自身不提供登录认证，不应把裸端口直接暴露到公网。

SQLite 数据、报告、日志和备份分别保存在 Docker 命名卷中，执行 `docker compose down` 或重建镜像不会删除。不要使用 `docker compose down -v`，除非明确要删除全部持久化数据。可在同一镜像和数据卷中手动运行数据任务：

```bash
docker compose run --rm dashboard stock-picker daily
docker compose run --rm dashboard stock-picker recommend --asset all
```

更新版本：

```bash
git pull
docker compose up -d --build
```

如需登录 Windows 后自动启动网站，只需注册一次：

```powershell
.\scripts\register_website.ps1
```

启动脚本会先检查本地健康状态，网站已运行时不会重复启动；自启动任务失败后会自动重试 3 次。

## 每日定时

确认手动 `daily` 成功后，在 PowerShell 中运行：

```powershell
.\scripts\register_task.ps1 -Time "18:30"
```

默认注册两个任务：A 股任务在工作日 18:30 运行，全球行情、用户基金、美债曲线与官方事件任务在工作日 08:30 运行。程序会检查共同数据日；数据不完整或明显陈旧时拒绝生成正式报告。日志保存在 `logs/`。

注册全量推荐流水线（工作日 22:30，基金日净值发布后运行）：

```powershell
.\scripts\register_recommendations.ps1 -Time "22:30"
```

计划任务仅允许单实例运行，失败后每 15 分钟重试，最多 3 次，单次最长 3 小时。

也可以随时手动运行。`--analyze-only` 会使用最近一次完整快照重新分析，不重新联网拉取：

```powershell
.\.venv\Scripts\stock-picker.exe recommend --asset all
.\.venv\Scripts\stock-picker.exe recommend --asset stock --analyze-only
.\.venv\Scripts\stock-picker.exe recommend --asset fund --analyze-only
```

安装每天 09:00 的本机重要事件桌面提醒：

```powershell
.\scripts\register_reminders.ps1 -Time "09:00"
```

提醒内容来自网站事件库。FOMC 会议并不等于一定加息或降息，决定必须以美联储正式声明为准。

## 数据验证与备份

离线测试：

```powershell
.\.venv\Scripts\python -m pytest -q
```

逐一验证全球指数、黄金期货、债券 ETF、港股、日股、美国财政部收益率、国内基金和 A 股财务的真实联网契约：

```powershell
py -3.12 scripts\smoke_live_data.py
```

持仓、成本、账户、笔记以明文保存在本机 SQLite，不应把数据库发送给他人。创建本机备份：

```powershell
.\scripts\backup_data.ps1
```

首次安装或移动项目后，收紧 Windows 数据目录权限：

```powershell
.\scripts\secure_local_data.ps1
```

当前备份同样是明文文件，请存放在受 BitLocker/EFS 等系统加密保护的位置。网站启动脚本和 `.streamlit/config.toml` 均强制只监听 `127.0.0.1`；若要外网访问，必须另行增加身份认证、TLS 和访问控制。

恢复前必须关闭网站；恢复脚本会校验备份、保留当前数据库安全副本，并以临时文件原子替换：

```powershell
.\scripts\restore_data.ps1 -BackupFile .\backups\stocks-YYYYMMDD-HHMMSS.db
```

## 常用命令

```powershell
# 只同步行情
.\.venv\Scripts\stock-picker.exe sync

# 只用本地数据重新评分
.\.venv\Scripts\stock-picker.exe select

# 同步并评分
.\.venv\Scripts\stock-picker.exe daily

# 测试
.\.venv\Scripts\python -m pytest
```

修改 [config.toml](config.toml) 可调整股票池规模、流动性门槛、候选数和权重。权重之和必须等于 1。

## 可选 AI 审阅

安装依赖并设置环境变量：

```powershell
.\.venv\Scripts\python -m pip install -e ".[ai]"
$env:OPENAI_API_KEY = "你的密钥"
```

再将 `config.toml` 中 `[ai] enabled` 改为 `true`。只有候选报告会发送给 API，本地全量行情不会上传。AI 只能复述和审阅报告内证据，不负责下单。

## 已知边界

- “全量”明确指免费数据源在该批次可见的沪深北 A 股和六类境内公募基金份额；全球页面仍是精选研究池。没有授权证券主数据前不会宣称覆盖全球全部股票和基金。
- A 股候选结合最近完整年度财务质量、行业内估值、趋势、回撤、波动与流动性；每行业先深度分析最多 15 只，再发布最多 5 只。北交所代码保留在全量快照，但当前免费历史行情路由不稳定，因此不会悄悄进入正式候选。
- 基金推荐使用累计净值计算总回报，使用单位净值计算持仓市值；两种口径分别存储。公开排行缺少完整管理费、销售服务费、规模和经理任期时会在风险中标注，不能将结果解释为完整基金尽调。
- 债券 ETF 页只比较价格总回报代理、波动和回撤，不提供久期、YTM、SEC 收益率或信用利差；商品页使用连续期货代理，不是现货或可直接用于持仓估值的具体期货合约。
- 交易账本保留成交日汇率审计轨迹，但持仓仍由持仓页维护；尚未根据不完整旧流水自动重建税务批次和历史 TWR/IRR。
- 免费行情接口可能限流或临时变更；程序会在东方财富失败时自动回退腾讯行情，数据库和 provider 也已分层，后续可替换为付费数据源。
- 半导体战况使用 Yahoo Finance 免费聚合行情，只能称近实时且可能延迟；海力士使用纳斯达克 ADR `SKHY`，并与其他三个标的统一按美股交易时段分析。综合分不是交易建议。
- 前复权数据适合研究连续收益，但不应与当时真实成交价混用。
- 模型未包含完整交易成本、组合约束与样本外回测，不能直接据此实盘。
