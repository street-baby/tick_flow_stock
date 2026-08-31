# 9:25 竞价抢筹因子研究与策略优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接入 Zhitu 真实集合竞价数据，建立无未来函数的训练/样本外回测，并用冻结后的可解释因子替换当前混用日线量比的竞价评分。

**Architecture:** Zhitu provider 只负责获取和规范化 `ov/bp`；`AuctionHistoryStore` 负责按交易日缓存；`auction_factor_research` 以纯函数构建特征、标签、训练规则和样本外报告；`AuctionService` 只消费明确的 `data_mode` 与冻结规则。历史竞价缺失时允许展示日线代理候选，但禁止计算真实竞价分数。

**Tech Stack:** Python 3.11、Polars、httpx、FastAPI、pytest、React、TypeScript、TanStack Query。

---

## 文件结构

- `backend/app/plugins/zhitu/client.py`：增加 Zhitu 集合竞价表现原始请求。
- `backend/app/plugins/zhitu/provider.py`：规范化为 `symbol/date/opening_auction_volume/auction_prev_volume_pct`。
- `backend/app/plugins/zhitu/plugin.yaml`：声明 `auction` 数据集。
- `backend/app/services/auction_history.py`：竞价分区缓存的唯一读写入口。
- `backend/app/services/auction_factor_research.py`：纯函数特征、标签、规则训练和评估。
- `backend/scripts/backfill_auction_history.py`：限速回填 Zhitu 历史竞价数据。
- `backend/scripts/research_auction_factors.py`：生成冻结规则与回测报告。
- `backend/app/services/auction_service.py`：保留用户去重意图，移除 `vol_ratio < 0.10` 阶段猜测，接入真实竞价字段与冻结规则。
- `backend/app/api/auction.py`：增加回测报告读取端点，并修正 AI 文案字段。
- `frontend/src/lib/api.ts`：扩展竞价结果和回测报告类型。
- `frontend/src/pages/AuctionSnatch.tsx`：展示数据模式、竞昨比、真实竞价额和验证结果。
- `backend/tests/test_zhitu_auction.py`：provider 契约测试。
- `backend/tests/test_auction_history.py`：缓存分区和去重测试。
- `backend/tests/test_auction_factor_research.py`：标签、防泄漏、训练/验证和统计测试。
- `backend/tests/test_auction_service.py`：生产筛选数据模式与评分回归测试。

### Task 1: Zhitu 集合竞价数据契约

**Files:**
- Modify: `backend/app/plugins/zhitu/client.py`
- Modify: `backend/app/plugins/zhitu/provider.py`
- Modify: `backend/app/plugins/zhitu/plugin.yaml`
- Create: `backend/tests/test_zhitu_auction.py`

- [ ] **Step 1: 写 provider 解析失败测试**

```python
def test_get_auction_performance_normalizes_only_signal_time_fields(monkeypatch):
    provider = ZhituProvider()
    monkeypatch.setattr(provider._client, "fetch_auction_performance", lambda *_args, **_kwargs: [
        {"t": "2026-08-31", "ov": 91600, "bp": 3.683096, "cv": 24464, "fv": 0},
    ])
    frame = provider.get_auction_performance(
        ["000560.SZ"], date(2026, 8, 31), date(2026, 8, 31)
    )
    assert frame.to_dicts() == [{
        "symbol": "000560.SZ",
        "date": date(2026, 8, 31),
        "opening_auction_volume": 91600.0,
        "auction_prev_volume_pct": 3.683096,
    }]
    assert "closing_auction_volume" not in frame.columns
```

- [ ] **Step 2: 运行测试并确认因方法不存在而失败**

Run: `cd backend && uv run pytest tests/test_zhitu_auction.py -q`

Expected: FAIL，提示 `fetch_auction_performance` 或 `get_auction_performance` 不存在。

- [ ] **Step 3: 实现客户端和 provider 最小契约**

```python
# client.py
def fetch_auction_performance(self, symbol: str, start: date, end: date) -> list[dict]:
    data = self.get_json(
        f"/hs/lup/auction/{to_standard_code(symbol)}",
        {"st": start.strftime("%Y%m%d"), "et": end.strftime("%Y%m%d")},
    )
    return data if isinstance(data, list) else []
```

Provider 使用 `_clean_num`，只输出 `ov`、`bp` 和日期；`cv/fv` 不进入信号数据契约。将 `_DATASETS` 和 `plugin.yaml` 的 datasets 增加 `auction`。

- [ ] **Step 4: 运行 provider 测试**

Run: `cd backend && uv run pytest tests/test_zhitu_auction.py tests/test_zhitu_provider.py -q`

Expected: PASS。

- [ ] **Step 5: 提交该独立契约**

仅暂存本任务四个文件；提交信息遵循根目录 Lore Commit Protocol，并记录官方接口 `/hs/lup/auction/{symbol}`。

### Task 2: 竞价历史缓存与同股同日去重

**Files:**
- Create: `backend/app/services/auction_history.py`
- Create: `backend/tests/test_auction_history.py`

- [ ] **Step 1: 写分区写入、读取和去重失败测试**

```python
def test_history_store_keeps_one_row_per_symbol_date(tmp_path):
    store = AuctionHistoryStore(tmp_path)
    store.write(pl.DataFrame([
        {"symbol": "000560.SZ", "date": date(2026, 8, 31),
         "opening_auction_volume": 100.0, "auction_prev_volume_pct": 1.0},
        {"symbol": "000560.SZ", "date": date(2026, 8, 31),
         "opening_auction_volume": 120.0, "auction_prev_volume_pct": 1.2},
    ]))
    result = store.read(date(2026, 8, 31), date(2026, 8, 31))
    assert result.height == 1
    assert result.row(0, named=True)["opening_auction_volume"] == 120.0
```

- [ ] **Step 2: 运行测试并确认类不存在**

Run: `cd backend && uv run pytest tests/test_auction_history.py -q`

Expected: FAIL，提示 `AuctionHistoryStore` 不存在。

- [ ] **Step 3: 实现原子分区缓存**

```python
class AuctionHistoryStore:
    COLUMNS = {
        "symbol": pl.String,
        "date": pl.Date,
        "opening_auction_volume": pl.Float64,
        "auction_prev_volume_pct": pl.Float64,
    }

    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "auction_history"

    def read(self, start: date, end: date, symbols: list[str] | None = None) -> pl.DataFrame:
        files = [
            self.root / f"date={value.isoformat()}" / "part.parquet"
            for value in (start + timedelta(days=i) for i in range((end - start).days + 1))
            if (self.root / f"date={value.isoformat()}" / "part.parquet").exists()
        ]
        if not files:
            return pl.DataFrame(schema=self.COLUMNS)
        frame = pl.concat([pl.read_parquet(path) for path in files], how="diagonal_relaxed")
        if symbols:
            frame = frame.filter(pl.col("symbol").is_in(symbols))
        return frame.sort(["date", "symbol"])

    def write(self, frame: pl.DataFrame) -> int:
        if frame.is_empty():
            return 0
        self.root.mkdir(parents=True, exist_ok=True)
        written = 0
        for day_frame in frame.partition_by("date", maintain_order=True):
            trade_date = day_frame.item(0, "date")
            directory = self.root / f"date={trade_date.isoformat()}"
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / "part.parquet"
            old = pl.read_parquet(target) if target.exists() else pl.DataFrame(schema=self.COLUMNS)
            merged = (
                pl.concat([old, day_frame], how="diagonal_relaxed")
                .sort("opening_auction_volume", descending=True)
                .unique(["symbol", "date"], keep="first")
                .sort("symbol")
            )
            temporary = directory / "part.parquet.tmp"
            merged.write_parquet(temporary)
            os.replace(temporary, target)
            written += day_frame.height
        return written
```

不得修改 `kline_daily_enriched`，也不得把竞价缓存混入日线 schema。

- [ ] **Step 4: 运行缓存测试**

Run: `cd backend && uv run pytest tests/test_auction_history.py -q`

Expected: PASS。

- [ ] **Step 5: 提交缓存边界**

只提交 `auction_history.py` 和对应测试，Lore `Directive` 说明该目录只允许存储 9:25 已知字段。

### Task 3: 无未来函数特征与标签

**Files:**
- Create: `backend/app/services/auction_factor_research.py`
- Create: `backend/tests/test_auction_factor_research.py`

- [ ] **Step 1: 写标签对齐和涨停价失败测试**

```python
def test_labels_use_t0_close_and_next_trading_day_high():
    panel = sample_panel([
        ("2026-08-28", 2.40, 2.64, 2.64),
        ("2026-08-31", 2.90, 2.90, 2.90),
    ], previous_close=2.40)
    labeled = build_labels(panel, {"000560.SZ": "我爱我家"})
    row = labeled.filter(pl.col("date") == date(2026, 8, 28)).row(0, named=True)
    assert row["limit_up_t0"] is True
    assert row["premium_high_t1"] == pytest.approx(9.84848)
    assert row["premium_2pct_t1"] is True
    assert row["joint_success"] is True
```

- [ ] **Step 2: 写特征防泄漏失败测试**

```python
def test_feature_frame_ignores_t0_close_high_volume_and_future_rows():
    first = build_feature_frame(panel_variant(t0_close=10, t0_high=10, t0_volume=100), auctions)
    second = build_feature_frame(panel_variant(t0_close=99, t0_high=99, t0_volume=999999), auctions)
    assert first.select(FEATURE_COLUMNS).equals(second.select(FEATURE_COLUMNS))
```

- [ ] **Step 3: 运行测试并确认函数不存在**

Run: `cd backend && uv run pytest tests/test_auction_factor_research.py -q`

Expected: FAIL。

- [ ] **Step 4: 实现特征、标签和 Wilson 区间纯函数**

```python
FEATURE_COLUMNS = (
    "open_gap_pct", "auction_prev_volume_pct", "auction_amount_wan",
    "auction_to_prev_amount_pct", "prev_return_pct", "prev_body_pct",
    "prev_close_position", "prev_volume_ratio_5d", "momentum_5d",
    "momentum_10d", "momentum_20d", "distance_to_20d_high_pct",
    "limit_up_count_20d", "industry_gap_median",
    "industry_strong_gap_ratio", "market_strong_gap_ratio",
)

def estimate_auction_amount_wan(opening_volume: pl.Expr, opening_price: pl.Expr) -> pl.Expr:
    return opening_volume * 100.0 * opening_price / 10_000.0

def build_feature_frame(daily: pl.DataFrame, auction: pl.DataFrame,
                        instruments: pl.DataFrame,
                        industries: pl.DataFrame) -> pl.DataFrame:
    ordered = daily.sort(["symbol", "date"])
    features = ordered.with_columns(
        pl.col("raw_close").shift(1).over("symbol").alias("_prev_close"),
        pl.col("open").shift(1).over("symbol").alias("_prev_open"),
        pl.col("high").shift(1).over("symbol").alias("_prev_high"),
        pl.col("low").shift(1).over("symbol").alias("_prev_low"),
        pl.col("volume").shift(1).over("symbol").alias("_prev_volume"),
        pl.col("amount").shift(1).over("symbol").alias("_prev_amount"),
        pl.col("volume").shift(2).rolling_mean(5).over("symbol").alias("_prior_volume_5d"),
        pl.col("high").shift(1).rolling_max(20).over("symbol").alias("_prior_high_20d"),
        (pl.col("consecutive_limit_ups") > 0).cast(pl.Int8)
        .shift(1).rolling_sum(20).over("symbol").alias("limit_up_count_20d"),
        pl.col("raw_close").shift(6).over("symbol").alias("_close_t_minus_6"),
        pl.col("raw_close").shift(11).over("symbol").alias("_close_t_minus_11"),
        pl.col("raw_close").shift(21).over("symbol").alias("_close_t_minus_21"),
    ).with_columns(
        ((pl.col("open") / pl.col("_prev_close") - 1.0) * 100).alias("open_gap_pct"),
        ((pl.col("_prev_close") / pl.col("raw_close").shift(2).over("symbol") - 1.0) * 100)
        .alias("prev_return_pct"),
        ((pl.col("_prev_close") - pl.col("_prev_open")).abs() / pl.col("_prev_close") * 100)
        .alias("prev_body_pct"),
        ((pl.col("_prev_close") - pl.col("_prev_low")) /
         (pl.col("_prev_high") - pl.col("_prev_low")).clip(1e-9, None))
        .alias("prev_close_position"),
        (pl.col("_prev_volume") / pl.col("_prior_volume_5d")).alias("prev_volume_ratio_5d"),
        ((pl.col("_prev_close") / pl.col("_close_t_minus_6") - 1.0) * 100).alias("momentum_5d"),
        ((pl.col("_prev_close") / pl.col("_close_t_minus_11") - 1.0) * 100).alias("momentum_10d"),
        ((pl.col("_prev_close") / pl.col("_close_t_minus_21") - 1.0) * 100).alias("momentum_20d"),
        ((pl.col("open") / pl.col("_prior_high_20d") - 1.0) * 100)
        .alias("distance_to_20d_high_pct"),
    ).join(auction, on=["symbol", "date"], how="inner").with_columns(
        estimate_auction_amount_wan(pl.col("opening_auction_volume"), pl.col("open"))
        .alias("auction_amount_wan"),
        (estimate_auction_amount_wan(pl.col("opening_auction_volume"), pl.col("open")) * 10_000 /
         pl.col("_prev_amount") * 100).alias("auction_to_prev_amount_pct"),
    )
    industry_map = industries.select("symbol", "industry").unique("symbol")
    features = features.join(industry_map, on="symbol", how="left")
    industry_stats = features.group_by("date", "industry").agg(
        pl.col("open_gap_pct").median().alias("industry_gap_median"),
        (pl.col("open_gap_pct") >= 2.0).mean().alias("industry_strong_gap_ratio"),
    )
    market_stats = features.group_by("date").agg(
        (pl.col("open_gap_pct") >= 2.0).mean().alias("market_strong_gap_ratio")
    )
    return (
        features.join(industry_stats, on=["date", "industry"], how="left")
        .join(market_stats, on="date", how="left")
        .select("symbol", "date", "industry", *FEATURE_COLUMNS)
    )

def build_labels(daily: pl.DataFrame, names: dict[str, str]) -> pl.DataFrame:
    ordered = daily.sort(["symbol", "date"]).with_columns(
        pl.col("raw_close").shift(1).over("symbol").alias("_prev_raw_close"),
        pl.col("open").shift(-1).over("symbol").alias("_next_open"),
        pl.col("high").shift(-1).over("symbol").alias("_next_high"),
        pl.col("date").shift(-1).over("symbol").alias("_next_date"),
    )
    name_frame = pl.DataFrame({"symbol": list(names), "name": list(names.values())})
    ordered = ordered.join(name_frame, on="symbol", how="left").with_columns(
        polars_price_limit_pct(
            pl.col("symbol"), pl.col("date"),
            polars_is_risk_warning_name(pl.col("name")),
        ).alias("_limit_pct")
    ).with_columns(
        polars_limit_price(pl.col("_prev_raw_close"), pl.col("_limit_pct"), up=True)
        .alias("_limit_up_price")
    ).with_columns(
        (pl.col("raw_close") >= pl.col("_limit_up_price") - 0.005).alias("limit_up_t0"),
        (pl.col("raw_high") >= pl.col("_limit_up_price") - 0.005).alias("touched_limit_up_t0"),
        ((pl.col("_next_open") / pl.col("raw_close") - 1.0) * 100).alias("premium_open_t1"),
        ((pl.col("_next_high") / pl.col("raw_close") - 1.0) * 100).alias("premium_high_t1"),
    ).with_columns(
        pl.when(pl.col("_next_date").is_not_null())
        .then(pl.col("premium_high_t1") >= 2.0).otherwise(None).alias("premium_2pct_t1")
    ).with_columns(
        pl.when(pl.col("premium_2pct_t1").is_not_null())
        .then(pl.col("limit_up_t0") & pl.col("premium_2pct_t1"))
        .otherwise(None).alias("joint_success")
    )
    return ordered.select(
        "symbol", "date", "limit_up_t0", "touched_limit_up_t0",
        "premium_open_t1", "premium_high_t1", "premium_2pct_t1", "joint_success",
    )

def wilson_interval(successes: int, observations: int, confidence: float = 0.95) -> tuple[float, float]:
    if observations <= 0:
        return 0.0, 0.0
    if confidence != 0.95:
        raise ValueError("only the pre-registered 95% interval is supported")
    z = 1.959963984540054
    n = float(observations)
    p = successes / n
    denominator = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denominator
    margin = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * n)) / n) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)
```

- [ ] **Step 5: 运行纯函数测试**

Run: `cd backend && uv run pytest tests/test_auction_factor_research.py -q`

Expected: PASS，且未来值变更不影响任何 `FEATURE_COLUMNS`。

- [ ] **Step 6: 提交研究核心**

提交纯函数模块和测试；Lore `Tested` 记录主板/创业板涨停价、跨周末 T+1 和防泄漏测试。

### Task 4: Zhitu 历史回填命令

**Files:**
- Create: `backend/scripts/backfill_auction_history.py`
- Modify: `backend/tests/test_zhitu_auction.py`

- [ ] **Step 1: 写批次重试与断点续传失败测试**

测试 `backfill(symbols, start, end, provider, store, requests_per_minute)`：已缓存的同股日期不重复请求；429/临时空响应最多重试三次；每批完成立即写分区。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/test_zhitu_auction.py -q`

Expected: FAIL，提示 `backfill` 不存在。

- [ ] **Step 3: 实现可恢复回填 CLI**

```bash
cd backend
uv run python -m scripts.backfill_auction_history \
  --start 2025-08-19 --end 2026-08-31 \
  --requests-per-minute 900 --resume
```

CLI 从 `KlineRepository.get_instruments_asset("stock")` 解析沪深 A 股代码；不输出 token；每 100 只报告完成数、有效行数和失败数；失败代码写入 `data/job_store/auction-backfill-failures.json` 以便安全重试。

- [ ] **Step 4: 运行单元测试和三个股票小样本试拉**

Run: `cd backend && uv run pytest tests/test_zhitu_auction.py tests/test_auction_history.py -q`

Run: `cd backend && uv run python -m scripts.backfill_auction_history --start 2026-08-31 --end 2026-08-31 --symbols 000560.SZ,002081.SZ,601595.SH --requests-per-minute 60`

Expected: 三只股票均写入一条记录；`bp` 约为 3.683096、2.762735、4.839528。

- [ ] **Step 5: 提交回填命令**

提交脚本和测试，不提交 `data/` 运行数据。

### Task 5: 训练冻结规则与样本外报告

**Files:**
- Modify: `backend/app/services/auction_factor_research.py`
- Modify: `backend/tests/test_auction_factor_research.py`
- Create: `backend/scripts/research_auction_factors.py`

- [ ] **Step 1: 写日期切分不可穿越失败测试**

```python
def test_fit_rule_never_reads_validation_labels():
    data = synthetic_research_frame()
    rule_a = fit_rule(data, validation_start=date(2026, 8, 3))
    changed = data.with_columns(
        pl.when(pl.col("date") >= date(2026, 8, 3)).then(~pl.col("joint_success"))
        .otherwise(pl.col("joint_success")).alias("joint_success")
    )
    rule_b = fit_rule(changed, validation_start=date(2026, 8, 3))
    assert rule_a == rule_b
```

- [ ] **Step 2: 实现可解释规则搜索**

规则网格只在训练期搜索：`open_gap_pct`、`auction_prev_volume_pct`、`auction_amount_wan`、竞价额/昨成交额、20 日涨停次数、20 日突破距离、行业强高开占比。目标排序依次为：训练联合成功数不少于 20、Wilson 下界、联合成功率、样本数；每天最多 Top 3。

```python
@dataclass(frozen=True)
class AuctionRule:
    min_gap_pct: float
    max_gap_pct: float
    min_auction_prev_volume_pct: float
    min_auction_amount_wan: float
    min_auction_to_prev_amount_pct: float
    min_industry_strong_gap_ratio: float
    max_distance_to_20d_high_pct: float
    top_n: int = 3
```

- [ ] **Step 3: 实现报告 CLI**

Run: `cd backend && uv run python -m scripts.research_auction_factors --validation-days 20 --top-n 1,2,3`

输出：

- `data/backtest_results/auction-factor-rule.json`：训练期冻结规则、数据版本和训练边界；
- `data/backtest_results/auction-factor-report.json`：基线/优化策略、样本数、T0 涨停率、T+1 指标、联合成功率、Wilson 区间、最大回撤和案例对比；
- 控制台打印三个案例与同日失败候选的主要因子差异。

- [ ] **Step 4: 运行测试与全年数据回填研究**

先完成 Task 4 的全量回填，再运行研究 CLI。验收必须记录实际结果；若样本外联合成功率低于 65%，报告 `target_met: false`，不得修改验证边界或重复搜索验证集。

- [ ] **Step 5: 提交研究脚本**

代码与测试提交；生成的数据报告不提交，除非仓库现有 `backtest_results` 规则明确要求版本化。

### Task 6: 生产筛选器接入显式数据模式

**Files:**
- Modify: `backend/app/services/auction_service.py`
- Create: `backend/tests/test_auction_service.py`

- [ ] **Step 1: 写数据模式和日线代理隔离失败测试**

```python
def test_daily_proxy_never_receives_auction_strength_score(service):
    result = service.run_auction_screener(as_of=date(2026, 8, 28), use_realtime=False)
    assert result["data_mode"] == "daily_proxy"
    assert all(row["auction_prev_volume_pct"] is None for row in result["rows"])
    assert all(row["qualified"] is False for row in result["rows"])
```

- [ ] **Step 2: 写历史真实竞价和实时阶段失败测试**

历史分区存在时返回 `historical_auction`；只有北京时间交易日 9:20 至 9:30 的 Zhitu 快照可返回 `live_auction`。不得再用 `vol_ratio < 0.10` 推断阶段。

- [ ] **Step 3: 运行测试并确认失败**

Run: `cd backend && uv run pytest tests/test_auction_service.py -q`

Expected: FAIL，当前返回值没有 `data_mode`，且代理数据仍会得到抢筹标签。

- [ ] **Step 4: 最小改造 AuctionService**

保留用户已有的两处去重和 `seen_symbols` 意图；将重复去重收敛为一个辅助函数。删除基于全天量比的竞价阶段判断，按以下来源赋值：

```python
if historical_auction.height:
    data_mode = "historical_auction"
elif is_live and is_opening_auction_window(now_cn):
    data_mode = "live_auction"
else:
    data_mode = "daily_proxy"
```

真实模式按冻结 `AuctionRule` 计算 `qualified`、`score`、`factor_contributions` 和 `risk_flags`；代理模式只展示形态候选并明确 `qualified=False`。

- [ ] **Step 5: 运行服务测试与现有 Zhitu 测试**

Run: `cd backend && uv run pytest tests/test_auction_service.py tests/test_auction_factor_research.py tests/test_zhitu_auction.py -q`

Expected: PASS。

- [ ] **Step 6: 提交生产服务改造**

暂存时逐块检查 `git diff --cached`，确保不覆盖用户未提交修改；Lore `Directive` 明确禁止恢复 `vol_ratio < 0.10` 阶段猜测。

### Task 7: API 与竞价页面证据展示

**Files:**
- Modify: `backend/app/api/auction.py`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/pages/AuctionSnatch.tsx`
- Create: `backend/tests/test_auction_api.py`

- [ ] **Step 1: 写报告端点和缺失报告失败测试**

端点 `GET /api/auction/backtest-report` 在报告存在时返回 JSON；缺失时返回 `status: "not_ready"`，不返回虚构胜率。

- [ ] **Step 2: 实现 API 和类型**

`AuctionStockRow` 增加 `auction_prev_volume_pct`、`opening_auction_volume`、`auction_amount_wan`、`qualified`、`factor_contributions`、`risk_flags`；`AuctionScreenResult` 增加 `data_mode`、`strategy_version`。AI 提示词只在真实模式下称为竞价抢筹。

- [ ] **Step 3: 更新页面**

页面首屏显示数据模式徽标；`daily_proxy` 使用警告文案“日线代理，不是历史 9:25 回测”；表格将旧“竞价量比”改为官方“竞昨比”；只把 `qualified=true` 标为推荐；回测摘要同时显示样本数、联合胜率和 Wilson 区间。

- [ ] **Step 4: 运行 API 测试与前端构建**

Run: `cd backend && uv run pytest tests/test_auction_api.py -q`

Run: `cd frontend && npm run build`

Expected: PASS；TypeScript 无类型错误。

- [ ] **Step 5: 提交 API 和页面**

只提交本任务四个文件，Lore `Tested` 写明 API 测试和前端构建。

### Task 8: 全量验证与结果复盘

**Files:**
- Review only: all files changed in Tasks 1-7

- [ ] **Step 1: 运行定向测试**

Run: `cd backend && uv run pytest tests/test_zhitu_auction.py tests/test_auction_history.py tests/test_auction_factor_research.py tests/test_auction_service.py tests/test_auction_api.py -q`

Expected: PASS。

- [ ] **Step 2: 运行静态检查**

Run: `cd backend && uv run ruff check app/plugins/zhitu app/services/auction_history.py app/services/auction_factor_research.py app/services/auction_service.py app/api/auction.py scripts/backfill_auction_history.py scripts/research_auction_factors.py tests/test_zhitu_auction.py tests/test_auction_history.py tests/test_auction_factor_research.py tests/test_auction_service.py tests/test_auction_api.py`

Expected: PASS。

- [ ] **Step 3: 运行前端构建**

Run: `cd frontend && npm run build`

Expected: PASS。

- [ ] **Step 4: 读取最终研究报告并核对三个案例**

确认 2026-08-31 三个案例只进入 T0 涨停复盘，不进入尚未产生的 T+1 联合胜率；对最近 20 个完整交易日逐日列出 Top N、成功/失败结果和失败因子。

- [ ] **Step 5: 检查工作区边界**

Run: `git status --short && git diff --check && git log --oneline -8`

Expected: 用户原有修改未被覆盖；没有 token、`data/` 回填文件、缓存或构建产物进入提交。

- [ ] **Step 6: 最终报告**

向用户报告真实样本外联合胜率、样本数、Wilson 区间、最大回撤、三个成功案例规律、失败候选共性、是否达到 65%，以及仍需继续积累的竞价历史长度。
