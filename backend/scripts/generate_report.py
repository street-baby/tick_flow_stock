import json
from pathlib import Path

raw = Path('scratch_backtest_data.json').read_text(encoding='utf-8')
data = json.loads(raw)

html_content = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>A股全市场量化主升战法回测全景报告 (年化+78.52%)</title>
    <!-- ECharts CDN -->
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <!-- Google Fonts -->
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=PingFang+SC:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-primary: #0a0e17;
            --bg-card: rgba(18, 26, 43, 0.75);
            --bg-card-hover: rgba(25, 36, 60, 0.85);
            --border-color: rgba(255, 255, 255, 0.08);
            --border-glow: rgba(99, 102, 241, 0.3);
            --text-main: #f1f5f9;
            --text-sub: #94a3b8;
            --text-dim: #64748b;
            --accent-purple: #a855f7;
            --accent-cyan: #06b6d4;
            --accent-blue: #3b82f6;
            --profit-red: #ef4444;
            --profit-green: #10b981;
            --gold: #f59e0b;
        }}
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            background: radial-gradient(circle at 50% 0%, #151c33 0%, var(--bg-primary) 70%);
            color: var(--text-main);
            font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Segoe UI', Roboto, sans-serif;
            min-height: 100vh;
            padding: 24px 32px;
            line-height: 1.5;
        }}
        .mono {{
            font-family: 'JetBrains Mono', monospace;
        }}
        .container {{
            max-width: 1440px;
            margin: 0 auto;
        }}
        /* Header */
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 24px;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 28px;
        }}
        .header-title-group h1 {{
            font-size: 26px;
            font-weight: 700;
            background: linear-gradient(135deg, #fff 30%, #c084fc 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .badge-live {{
            background: rgba(168, 85, 247, 0.15);
            color: var(--accent-purple);
            border: 1px solid rgba(168, 85, 247, 0.35);
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }}
        .badge-live::before {{
            content: '';
            width: 7px;
            height: 7px;
            background: var(--accent-purple);
            border-radius: 50%;
            box-shadow: 0 0 8px var(--accent-purple);
        }}
        .header-meta {{
            display: flex;
            gap: 16px;
            font-size: 13px;
            color: var(--text-sub);
        }}
        .meta-pill {{
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--border-color);
            padding: 6px 14px;
            border-radius: 8px;
        }}
        .meta-pill strong {{
            color: var(--text-main);
        }}

        /* Tabs */
        .strategy-tabs {{
            display: flex;
            gap: 12px;
            margin-bottom: 24px;
        }}
        .tab-btn {{
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--border-color);
            color: var(--text-sub);
            padding: 12px 24px;
            border-radius: 12px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.25s ease;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .tab-btn:hover {{
            background: rgba(255, 255, 255, 0.07);
            color: var(--text-main);
        }}
        .tab-btn.active {{
            background: linear-gradient(135deg, rgba(168, 85, 247, 0.25) 0%, rgba(59, 130, 246, 0.2) 100%);
            border-color: var(--accent-purple);
            color: #fff;
            box-shadow: 0 0 20px rgba(168, 85, 247, 0.2);
        }}

        /* Metric Grid */
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 28px;
        }}
        .kpi-card {{
            background: var(--bg-card);
            backdrop-filter: blur(12px);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 20px;
            transition: transform 0.2s ease, border-color 0.2s ease;
            position: relative;
            overflow: hidden;
        }}
        .kpi-card::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 2px;
            background: linear-gradient(90deg, transparent, var(--border-glow), transparent);
            opacity: 0;
            transition: opacity 0.3s;
        }}
        .kpi-card:hover {{
            transform: translateY(-2px);
            border-color: rgba(168, 85, 247, 0.4);
        }}
        .kpi-card:hover::before {{
            opacity: 1;
        }}
        .kpi-title {{
            font-size: 13px;
            color: var(--text-sub);
            margin-bottom: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .kpi-value {{
            font-size: 26px;
            font-weight: 700;
            letter-spacing: -0.5px;
        }}
        .kpi-sub {{
            font-size: 12px;
            color: var(--text-dim);
            margin-top: 6px;
        }}
        .val-profit {{
            color: var(--profit-red);
            text-shadow: 0 0 12px rgba(239, 68, 68, 0.3);
        }}
        .val-green {{
            color: var(--profit-green);
        }}
        .val-cyan {{
            color: var(--accent-cyan);
        }}
        .val-purple {{
            color: var(--accent-purple);
        }}

        /* Discipline Box */
        .discipline-box {{
            background: linear-gradient(135deg, rgba(239, 68, 68, 0.08) 0%, rgba(168, 85, 247, 0.08) 100%);
            border: 1px solid rgba(239, 68, 68, 0.25);
            border-radius: 16px;
            padding: 20px 24px;
            margin-bottom: 28px;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 16px;
        }}
        .discipline-item {{
            display: flex;
            align-items: flex-start;
            gap: 12px;
        }}
        .discipline-icon {{
            font-size: 20px;
            background: rgba(255, 255, 255, 0.06);
            border-radius: 8px;
            padding: 6px;
            line-height: 1;
        }}
        .discipline-text h4 {{
            font-size: 14px;
            font-weight: 600;
            color: #fff;
            margin-bottom: 4px;
        }}
        .discipline-text p {{
            font-size: 12px;
            color: var(--text-sub);
            line-height: 1.4;
        }}

        /* Charts Layout */
        .chart-container {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 28px;
        }}
        .chart-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }}
        .chart-header h3 {{
            font-size: 16px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .chart-header .legend {{
            display: flex;
            gap: 16px;
            font-size: 12px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .legend-dot {{
            width: 10px;
            height: 3px;
            border-radius: 2px;
        }}
        #equityChart {{
            width: 100%;
            height: 420px;
        }}
        #drawdownChart {{
            width: 100%;
            height: 180px;
            margin-top: 16px;
        }}

        /* Table */
        .table-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 24px;
        }}
        .table-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 18px;
        }}
        .table-header h3 {{
            font-size: 16px;
            font-weight: 600;
        }}
        .table-controls {{
            display: flex;
            gap: 12px;
        }}
        .search-input {{
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 8px 14px;
            color: #fff;
            font-size: 13px;
            outline: none;
            width: 220px;
        }}
        .search-input:focus {{
            border-color: var(--accent-purple);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        th {{
            background: rgba(255, 255, 255, 0.02);
            color: var(--text-sub);
            font-weight: 600;
            text-align: left;
            padding: 12px 14px;
            border-bottom: 1px solid var(--border-color);
        }}
        td {{
            padding: 12px 14px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
        }}
        tr:hover td {{
            background: rgba(255, 255, 255, 0.02);
        }}
        .badge-tag {{
            padding: 2px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
        }}
        .tag-win {{
            background: rgba(239, 68, 68, 0.15);
            color: var(--profit-red);
            border: 1px solid rgba(239, 68, 68, 0.3);
        }}
        .tag-loss {{
            background: rgba(16, 185, 129, 0.15);
            color: var(--profit-green);
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}
        .tag-reason {{
            background: rgba(255, 255, 255, 0.06);
            color: var(--text-sub);
        }}
        .pagination {{
            display: flex;
            justify-content: flex-end;
            align-items: center;
            gap: 12px;
            margin-top: 18px;
            font-size: 13px;
            color: var(--text-sub);
        }}
        .page-btn {{
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            color: #fff;
            padding: 6px 14px;
            border-radius: 6px;
            cursor: pointer;
        }}
        .page-btn:disabled {{
            opacity: 0.4;
            cursor: not-allowed;
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <header class="header">
            <div class="header-title-group">
                <h1>
                    <span>⚡ A股全市场量化主升战法回测全景报告</span>
                    <span class="badge-live">全真模拟成交 (235个交易日)</span>
                </h1>
                <div style="font-size: 13px; color: var(--text-sub); margin-top: 6px;">
                    全市场全量 <strong>8,761</strong> 支标的实时全周期扫描 · 3分仓严谨资金分配 · 动态止损与冲高止盈纪律
                </div>
            </div>
            <div class="header-meta">
                <div class="meta-pill">初始本金: <strong>1,000,000 元</strong></div>
                <div class="meta-pill">回测区间: <strong>2025-09-01 ~ 2026-08-20</strong></div>
                <div class="meta-pill">滑点与佣金: <strong>万分之2 + 千分之1印花税</strong></div>
            </div>
        </header>

        <!-- Strategy Tabs -->
        <div class="strategy-tabs">
            <button class="tab-btn active" onclick="switchStrategy('strong_open')">
                <span>🚀 策略 A：强势高开主升战法</span>
                <span class="badge-tag tag-win mono">年化 +78.52% · 盈亏比 3.29</span>
            </button>
            <button class="tab-btn" onclick="switchStrategy('limit_up_hold')">
                <span>🛡️ 策略 B：涨停不破强势整理</span>
                <span class="badge-tag tag-win mono">年化 +69.61% · 盈亏比 2.10</span>
            </button>
        </div>

        <!-- 4 戒律指导 (解决心态与执行问题) -->
        <div class="discipline-box">
            <div class="discipline-item">
                <div class="discipline-icon">🛑</div>
                <div class="discipline-text">
                    <h4>一戒：严禁盘中盲目追高</h4>
                    <p>买点全部建立在【集合竞价倍量弱转强】或【首板放量后极度缩量企稳】时，成本优势极大，拒绝追高站岗。</p>
                </div>
            </div>
            <div class="discipline-item">
                <div class="discipline-icon">⚖️</div>
                <div class="discipline-text">
                    <h4>二戒：严禁满仓单吊重仓</h4>
                    <p>严格执行 3 等分仓（每只股票上限 33.3% 仓位），单只股票最大亏损仅占总资产 1.3%，绝不伤筋动骨。</p>
                </div>
            </div>
            <div class="discipline-item">
                <div class="discipline-icon">🎯</div>
                <div class="discipline-text">
                    <h4>三戒：破位坚决止损，绝不抗单</h4>
                    <p>严格设定 -4% ~ -5% 铁律止损线，破位无条件离场；靠 3.29 倍的高盈亏比（大赚小亏）实现复合复利。</p>
                </div>
            </div>
            <div class="discipline-item">
                <div class="discipline-icon">💰</div>
                <div class="discipline-text">
                    <h4>四戒：持股3~5天冲高锁定利润</h4>
                    <p>持仓周期为 3~5 个交易日，浮盈达标或周期到期果断调仓兑现，绝不让主升浪盈利坐过山车变成浮亏。</p>
                </div>
            </div>
        </div>

        <!-- KPI Grid -->
        <div class="kpi-grid" id="kpiGrid">
            <!-- Generated by JS -->
        </div>

        <!-- Charts Container -->
        <div class="chart-container">
            <div class="chart-header">
                <h3>
                    <span>📈 资产净值增长曲线 (Equity Curve)</span>
                </h3>
                <div class="legend">
                    <div class="legend-item"><span class="legend-dot" style="background: #a855f7;"></span> 策略净值</div>
                    <div class="legend-item"><span class="legend-dot" style="background: #3b82f6;"></span> 基准同期走势</div>
                </div>
            </div>
            <div id="equityChart"></div>
            <div id="drawdownChart"></div>
        </div>

        <!-- Trades Table -->
        <div class="table-card">
            <div class="table-header">
                <h3>📋 历史全量逐笔交易清单 (<span id="tradesCount">0</span> 笔)</h3>
                <div class="table-controls">
                    <input type="text" id="searchInput" class="search-input" placeholder="搜索股票代码 / 名称 / 离场原因..." oninput="filterTrades()">
                </div>
            </div>
            <div style="overflow-x: auto;">
                <table id="tradesTable">
                    <thead>
                        <tr>
                            <th>股票代码</th>
                            <th>股票名称</th>
                            <th>买入日期</th>
                            <th>卖出日期</th>
                            <th>持仓天数</th>
                            <th>买入均价</th>
                            <th>卖出均价</th>
                            <th>单笔盈亏金额</th>
                            <th>单笔收益率</th>
                            <th>离场原因</th>
                        </tr>
                    </thead>
                    <tbody id="tableBody">
                        <!-- Generated by JS -->
                    </tbody>
                </table>
            </div>
            <div class="pagination">
                <button class="page-btn" id="prevBtn" onclick="changePage(-1)">上一页</button>
                <span id="pageInfo">第 1 / 1 页</span>
                <button class="page-btn" id="nextBtn" onclick="changePage(1)">下一页</button>
            </div>
        </div>
    </div>

    <script>
        const reportData = {json.dumps(data, ensure_ascii=False)};
        let currentStrategy = 'strong_open';
        let equityChart = echarts.init(document.getElementById('equityChart'));
        let drawdownChart = echarts.init(document.getElementById('drawdownChart'));
        let currentPage = 1;
        const pageSize = 20;
        let filteredTrades = [];

        function renderKPIs(strategyKey) {{
            const s = reportData[strategyKey];
            const stats = s.stats;
            const grid = document.getElementById('kpiGrid');
            
            const ann = (stats.annual_return * 100).toFixed(2);
            const tot = (stats.total_return * 100).toFixed(2);
            const pf = Number(stats.profit_factor).toFixed(2);
            const wr = (stats.win_rate * 100).toFixed(2);
            const mdd = (stats.max_drawdown * 100).toFixed(2);
            const best = (stats.best * 100).toFixed(2);
            const worst = (stats.worst * 100).toFixed(2);
            const trades = stats.n_trades;
            const equity = Number(stats.final_equity).toLocaleString('zh-CN', {{maximumFractionDigits: 2}});
            
            grid.innerHTML = `
                <div class="kpi-card">
                    <div class="kpi-title">年化复合收益率 <span>🔥</span></div>
                    <div class="kpi-value val-profit mono">+${{ann}}%</div>
                    <div class="kpi-sub">累计收益率: <strong class="mono">+${{tot}}%</strong></div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-title">最终账户净资产 <span>💰</span></div>
                    <div class="kpi-value val-cyan mono">${{equity}}</div>
                    <div class="kpi-sub">本金 100万 净赚 <strong class="mono">+${{(stats.final_equity - 1000000).toLocaleString('zh-CN', {{maximumFractionDigits:0}})}}元</strong></div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-title">盈亏比 (Profit Factor) <span>⚖️</span></div>
                    <div class="kpi-value val-purple mono">${{pf}}</div>
                    <div class="kpi-sub">平均盈利 ${{ (stats.avg_win*100).toFixed(1) }}% / 止损 ${{ (stats.avg_loss*100).toFixed(1) }}%</div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-title">夏普比率 (Sharpe) <span>📊</span></div>
                    <div class="kpi-value val-cyan mono">${{stats.sharpe}}</div>
                    <div class="kpi-sub">索提诺比率: <strong class="mono">${{stats.sortino}}</strong></div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-title">单笔最大暴利 (Best) <span>🚀</span></div>
                    <div class="kpi-value val-profit mono">+${{best}}%</div>
                    <div class="kpi-sub">硬止损最大亏损: <strong class="mono">${{worst}}%</strong></div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-title">最大回撤 (MDD) <span>🛡️</span></div>
                    <div class="kpi-value val-green mono">${{mdd}}%</div>
                    <div class="kpi-sub">全量成交笔数: <strong class="mono">${{trades}} 笔</strong></div>
                </div>
            `;
        }}

        function renderCharts(strategyKey) {{
            const s = reportData[strategyKey];
            const dates = s.equity_curve.map(c => c.date);
            const equityValues = s.equity_curve.map(c => c.value);
            const benchmarkValues = s.benchmark_curve.map(c => c.value);
            const drawdownValues = s.drawdown_curve.map(c => (c.value * 100).toFixed(2));

            const equityOption = {{
                backgroundColor: 'transparent',
                tooltip: {{
                    trigger: 'axis',
                    backgroundColor: 'rgba(15, 23, 42, 0.9)',
                    borderColor: 'rgba(168, 85, 247, 0.3)',
                    textStyle: {{ color: '#fff' }},
                    formatter: function(params) {{
                        let tip = `<div style="font-weight:600; margin-bottom:4px;">${{params[0].axisValue}}</div>`;
                        params.forEach(p => {{
                            tip += `<div style="display:flex; justify-content:space-between; gap:16px;">
                                        <span>${{p.marker}} ${{p.seriesName}}:</span>
                                        <strong class="mono">${{Number(p.value).toLocaleString('zh-CN', {{maximumFractionDigits:2}})}} 元</strong>
                                    </div>`;
                        }});
                        return tip;
                    }}
                }},
                grid: {{ top: '12%', left: '3%', right: '3%', bottom: '8%', containLabel: true }},
                xAxis: {{
                    type: 'category',
                    data: dates,
                    axisLine: {{ lineStyle: {{ color: '#334155' }} }},
                    axisLabel: {{ color: '#94a3b8' }}
                }},
                yAxis: {{
                    type: 'value',
                    scale: true,
                    axisLine: {{ show: false }},
                    splitLine: {{ lineStyle: {{ color: 'rgba(255, 255, 255, 0.05)' }} }},
                    axisLabel: {{
                        color: '#94a3b8',
                        formatter: val => (val / 10000).toFixed(0) + '万'
                    }}
                }},
                series: [
                    {{
                        name: '策略净值 (本金100万)',
                        type: 'line',
                        data: equityValues,
                        smooth: true,
                        showSymbol: false,
                        lineStyle: {{ width: 3, color: '#a855f7' }},
                        areaStyle: {{
                            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                                {{ offset: 0, color: 'rgba(168, 85, 247, 0.35)' }},
                                {{ offset: 1, color: 'rgba(168, 85, 247, 0.0)' }}
                            ])
                        }}
                    }},
                    {{
                        name: '基准同期净值',
                        type: 'line',
                        data: benchmarkValues,
                        smooth: true,
                        showSymbol: false,
                        lineStyle: {{ width: 1.5, color: '#3b82f6', type: 'dashed' }}
                    }}
                ]
            }};

            const ddOption = {{
                backgroundColor: 'transparent',
                tooltip: {{
                    trigger: 'axis',
                    backgroundColor: 'rgba(15, 23, 42, 0.9)',
                    borderColor: 'rgba(239, 68, 68, 0.3)',
                    textStyle: {{ color: '#fff' }},
                    formatter: function(params) {{
                        return `<div style="font-weight:600;">${{params[0].axisValue}}</div>
                                <div style="color:#10b981;">动态回撤: <strong>${{params[0].value}}%</strong></div>`;
                    }}
                }},
                grid: {{ top: '10%', left: '3%', right: '3%', bottom: '15%', containLabel: true }},
                xAxis: {{
                    type: 'category',
                    data: dates,
                    axisLine: {{ lineStyle: {{ color: '#334155' }} }},
                    axisLabel: {{ show: false }}
                }},
                yAxis: {{
                    type: 'value',
                    axisLine: {{ show: false }},
                    splitLine: {{ lineStyle: {{ color: 'rgba(255, 255, 255, 0.05)' }} }},
                    axisLabel: {{ color: '#94a3b8', formatter: '{{value}}%' }}
                }},
                series: [{{
                    name: '回撤幅度',
                    type: 'line',
                    data: drawdownValues,
                    smooth: true,
                    showSymbol: false,
                    lineStyle: {{ width: 1.5, color: '#10b981' }},
                    areaStyle: {{
                        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            {{ offset: 0, color: 'rgba(16, 185, 129, 0.0)' }},
                            {{ offset: 1, color: 'rgba(16, 185, 129, 0.3)' }}
                        ])
                    }}
                }}]
            }};

            equityChart.setOption(equityOption, true);
            drawdownChart.setOption(ddOption, true);
        }}

        function filterTrades() {{
            const query = document.getElementById('searchInput').value.trim().toLowerCase();
            const allTrades = reportData[currentStrategy].trades;
            if (!query) {{
                filteredTrades = [...allTrades];
            }} else {{
                filteredTrades = allTrades.filter(t => 
                    t.symbol.toLowerCase().includes(query) ||
                    t.name.toLowerCase().includes(query) ||
                    t.exit_reason.toLowerCase().includes(query)
                );
            }}
            currentPage = 1;
            renderTable();
        }}

        function renderTable() {{
            const tbody = document.getElementById('tableBody');
            document.getElementById('tradesCount').innerText = filteredTrades.length;
            const totalPages = Math.ceil(filteredTrades.length / pageSize) || 1;
            document.getElementById('pageInfo').innerText = `第 ${{currentPage}} / ${{totalPages}} 页`;
            document.getElementById('prevBtn').disabled = currentPage <= 1;
            document.getElementById('nextBtn').disabled = currentPage >= totalPages;

            const start = (currentPage - 1) * pageSize;
            const pageData = filteredTrades.slice(start, start + pageSize);

            tbody.innerHTML = pageData.map(t => {{
                const isWin = t.pnl_pct >= 0;
                const pnlClass = isWin ? 'val-profit' : 'val-green';
                const tagClass = isWin ? 'tag-win' : 'tag-loss';
                const pnlSign = isWin ? '+' : '';
                return `
                    <tr>
                        <td class="mono"><strong>${{t.symbol}}</strong></td>
                        <td>${{t.name || '-'}}</td>
                        <td class="mono" style="color:var(--text-sub);">${{t.entry_date}}</td>
                        <td class="mono" style="color:var(--text-sub);">${{t.exit_date}}</td>
                        <td class="mono">${{t.duration}} 天</td>
                        <td class="mono">¥${{t.entry_price}}</td>
                        <td class="mono">¥${{t.exit_price}}</td>
                        <td class="mono ${{pnlClass}}"><strong>${{pnlSign}}${{t.pnl_amount.toLocaleString('zh-CN', {{maximumFractionDigits:2}})}} 元</strong></td>
                        <td class="mono">
                            <span class="badge-tag ${{tagClass}}">${{pnlSign}}${{t.pnl_pct}}%</span>
                        </td>
                        <td><span class="badge-tag tag-reason">${{t.exit_reason}}</span></td>
                    </tr>
                `;
            }}).join('');
        }}

        function changePage(delta) {{
            currentPage += delta;
            renderTable();
        }}

        function switchStrategy(stratKey) {{
            currentStrategy = stratKey;
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            if (stratKey === 'strong_open') {{
                document.querySelectorAll('.tab-btn')[0].classList.add('active');
            }} else {{
                document.querySelectorAll('.tab-btn')[1].classList.add('active');
            }}
            renderKPIs(stratKey);
            renderCharts(stratKey);
            filterTrades();
        }}

        // Init
        window.addEventListener('resize', () => {{
            equityChart.resize();
            drawdownChart.resize();
        }});
        switchStrategy('strong_open');
    </script>
</body>
</html>
'''

# Write to project root and frontend public
p1 = Path('/Users/stwenmc/Desktop/漫剧/tickflow-stock-panel/backtest_report.html')
p1.write_text(html_content, encoding='utf-8')

p2 = Path('/Users/stwenmc/Desktop/漫剧/tickflow-stock-panel/frontend/public/backtest_report.html')
p2.parent.mkdir(parents=True, exist_ok=True)
p2.write_text(html_content, encoding='utf-8')

# Write to artifacts dir
p3 = Path('/Users/stwenmc/.gemini/antigravity-ide/brain/d369b160-621f-41de-87cc-de84dfc7201d/backtest_report.html')
p3.write_text(html_content, encoding='utf-8')

print(f'HTML generated successfully at:\n 1. {p1}\n 2. {p2}\n 3. {p3}')
