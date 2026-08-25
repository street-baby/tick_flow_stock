"""生成【亿利达与连板主升战法】全景量化回测 HTML 报告 (年化+78.52% / +69.61%)"""
import json
from pathlib import Path

raw = Path('scratch_backtest_data.json').read_text(encoding='utf-8')
data = json.loads(raw)

html_content = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>【亿利达与连板主升战法】全景量化回测报告 (年化+78.52%)</title>
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

        /* Strategy Switcher Tabs */
        .tabs-nav {{
            display: flex;
            gap: 12px;
            margin-bottom: 24px;
        }}
        .tab-button {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            color: var(--text-sub);
            padding: 12px 24px;
            border-radius: 12px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .tab-button:hover {{
            background: var(--bg-card-hover);
            border-color: var(--border-glow);
            color: var(--text-main);
        }}
        .tab-button.active {{
            background: linear-gradient(135deg, rgba(168, 85, 247, 0.2) 0%, rgba(59, 130, 246, 0.2) 100%);
            border-color: var(--accent-purple);
            color: #fff;
            box-shadow: 0 0 20px rgba(168, 85, 247, 0.2);
        }}

        /* Key Metrics Grid */
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(6, 1fr);
            gap: 16px;
            margin-bottom: 24px;
        }}
        .metric-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 20px 18px;
            position: relative;
            overflow: hidden;
            backdrop-filter: blur(12px);
        }}
        .metric-card::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 2px;
            background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.1), transparent);
        }}
        .metric-card.highlight {{
            border-color: rgba(239, 68, 68, 0.4);
            box-shadow: 0 4px 24px -6px rgba(239, 68, 68, 0.25);
        }}
        .metric-label {{
            font-size: 12px;
            color: var(--text-sub);
            margin-bottom: 8px;
            font-weight: 500;
        }}
        .metric-value {{
            font-size: 24px;
            font-weight: 700;
            line-height: 1.1;
        }}
        .metric-value.profit {{ color: var(--profit-red); }}
        .metric-value.cyan {{ color: var(--accent-cyan); }}
        .metric-value.purple {{ color: var(--accent-purple); }}
        .metric-value.gold {{ color: var(--gold); }}
        .metric-sub {{
            font-size: 11px;
            color: var(--text-dim);
            margin-top: 6px;
        }}

        /* Logic Analysis Card */
        .logic-card {{
            background: linear-gradient(135deg, rgba(24, 32, 54, 0.8) 0%, rgba(15, 23, 42, 0.9) 100%);
            border: 1px solid rgba(168, 85, 247, 0.3);
            border-radius: 18px;
            padding: 22px 28px;
            margin-bottom: 24px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }}
        .logic-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 16px;
        }}
        .logic-header h2 {{
            font-size: 16px;
            font-weight: 700;
            color: #c084fc;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .logic-steps {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
        }}
        .logic-step {{
            background: rgba(10, 14, 23, 0.6);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 16px;
        }}
        .logic-step .step-title {{
            font-size: 13px;
            font-weight: 700;
            color: var(--text-main);
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .logic-step .step-desc {{
            font-size: 12px;
            color: var(--text-sub);
            line-height: 1.5;
        }}

        /* Charts Grid */
        .charts-container {{
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 20px;
            margin-bottom: 24px;
        }}
        .chart-section {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 24px;
            backdrop-filter: blur(12px);
        }}
        .chart-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }}
        .chart-title {{
            font-size: 16px;
            font-weight: 600;
            color: var(--text-main);
        }}
        .chart-wrapper {{
            width: 100%;
            height: 380px;
        }}

        /* Trade Logs Table */
        .trades-section {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 24px;
            backdrop-filter: blur(12px);
        }}
        .trades-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 18px;
        }}
        .trades-title {{
            font-size: 16px;
            font-weight: 600;
        }}
        .table-filter-input {{
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            padding: 8px 16px;
            border-radius: 8px;
            color: var(--text-main);
            font-size: 13px;
            outline: none;
            width: 220px;
        }}
        .trades-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        .trades-table th {{
            text-align: left;
            padding: 12px 14px;
            color: var(--text-dim);
            font-weight: 600;
            border-bottom: 1px solid var(--border-color);
            font-size: 12px;
            text-transform: uppercase;
        }}
        .trades-table td {{
            padding: 12px 14px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.03);
        }}
        .trades-table tr:hover td {{
            background: rgba(255, 255, 255, 0.02);
        }}
        .badge-pnl {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 700;
        }}
        .badge-pnl.win {{
            background: rgba(239, 68, 68, 0.15);
            color: #f87171;
            border: 1px solid rgba(239, 68, 68, 0.3);
        }}
        .badge-pnl.loss {{
            background: rgba(16, 185, 129, 0.15);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.3);
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
        .btn-page {{
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
        }}
        .btn-page:disabled {{
            opacity: 0.3;
            cursor: not-allowed;
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <div class="header-title-group">
                <h1>
                    <span>🏆 【亿利达与连板主升战法】全景量化回测报告</span>
                    <span class="badge-live">已通过全市场8761支股票撮合检验</span>
                </h1>
                <p style="color: var(--text-sub); font-size: 13px; margin-top: 6px;">
                    数据周期：2025-09-01 ~ 2026-08-20 (全年235个交易日) · 初始本金 100 万元 · 包含印花税/佣金/真实滑点
                </p>
            </div>
            <div class="header-meta">
                <div class="meta-pill">全市场股票：<strong class="mono" style="color: var(--accent-cyan);">8,761</strong> 支</div>
                <div class="meta-pill">最大单笔暴利：<strong class="mono" style="color: var(--profit-red);">+107.50%</strong></div>
            </div>
        </div>

        <!-- Strategy Tabs -->
        <div class="tabs-nav">
            <button class="tab-button active" onclick="setStrategy('strong_open')">
                <span>🚀 战法 A：竞价弱转强高开抢筹 (年化 +78.52% · 盈亏比 3.29)</span>
            </button>
            <button class="tab-button" onclick="setStrategy('limit_up_hold')">
                <span>🛡️ 战法 B：涨停不破强势整理 (亿利达/卓翼科技主升战法 · 年化 +69.61%)</span>
            </button>
        </div>

        <!-- 亿利达操盘逻辑拆解 -->
        <div class="logic-card">
            <div class="logic-header">
                <h2>🎯 亿利达（002686）与 卓翼科技（002369）强庄操盘四大密码</h2>
                <span style="font-size: 12px; color: #a855f7;">为什么普通抄底亏损，而强庄主升大赚？</span>
            </div>
            <div class="logic-steps">
                <div class="logic-step">
                    <div class="step-title">① 涨停基因启动</div>
                    <div class="step-desc">底部爆出巨量红柱，首板涨停强行扫荡低位筹码，股价迅速脱离亏损区，建立主力底仓成本。</div>
                </div>
                <div class="logic-step">
                    <div class="step-title">② 涨停底线绝不跌破</div>
                    <div class="step-desc">洗盘时股价死死守在首板涨停价上方（如卓翼科技在5.90元单峰密集），强庄绝不允许散户低价买筹。</div>
                </div>
                <div class="logic-step">
                    <div class="step-title">③ 涨幅 &lt; 30% 受控蓄势</div>
                    <div class="step-desc">累计涨幅死死压在 30% 以内反复揉搓，成交量缩至 1/3 地量，浮动筹码彻底洗净，抛压完全真空。</div>
                </div>
                <div class="logic-step">
                    <div class="step-title">④ 次日竞价抢筹拉连板</div>
                    <div class="step-desc">次日早盘 9:25 集合竞价高开弱转强（放量高开 +2%），主力瞬间点火封涨停，正式开启连板主升浪。</div>
                </div>
            </div>
        </div>

        <!-- Metrics Grid -->
        <div class="metrics-grid">
            <div class="metric-card highlight">
                <div class="metric-label">年化复合收益率 (Annual Return)</div>
                <div class="metric-value profit mono" id="m-annual">+78.52%</div>
                <div class="metric-sub" id="m-total">总收益: +71.67%</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">盈亏比 (Profit Factor)</div>
                <div class="metric-value purple mono" id="m-pf">3.29</div>
                <div class="metric-sub">每亏 1 元赚 3.29 元</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">最终资产 / 净利润</div>
                <div class="metric-value profit mono" id="m-equity">1,716,718 元</div>
                <div class="metric-sub" id="m-profit">净赚 +71.67 万元</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">总交易笔数 / 胜率</div>
                <div class="metric-value cyan mono" id="m-trades">293 笔</div>
                <div class="metric-sub" id="m-win">胜率: 26.62% (高盈亏比盈利)</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">单笔最大暴利 (Best Trade)</div>
                <div class="metric-value profit mono" id="m-best">+107.50%</div>
                <div class="metric-sub" id="m-hold">平均持仓: 2.4 天</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">夏普比率 / 索提诺比率</div>
                <div class="metric-value gold mono" id="m-sharpe">1.09</div>
                <div class="metric-sub" id="m-sortino">Sortino: 1.60</div>
            </div>
        </div>

        <!-- Charts Grid -->
        <div class="charts-container">
            <div class="chart-section">
                <div class="chart-header">
                    <div class="chart-title">📈 资产净值走势曲线 (vs 全市场等权基准)</div>
                </div>
                <div id="chart-main" class="chart-wrapper"></div>
            </div>
            <div class="chart-section">
                <div class="chart-header">
                    <div class="chart-title">📉 动态最大回撤曲线</div>
                </div>
                <div id="chart-dd" class="chart-wrapper"></div>
            </div>
        </div>

        <!-- Trade Logs Table -->
        <div class="trades-section">
            <div class="trades-header">
                <div class="trades-title">📋 逐笔实战交易记录清单 (全市场真实撮合)</div>
                <input type="text" id="filterInput" class="table-filter-input mono" placeholder="搜索股票代码 / 名称..." oninput="onFilterChange()">
            </div>
            <table class="trades-table">
                <thead>
                    <tr>
                        <th>代码</th>
                        <th>名称</th>
                        <th>买入日期</th>
                        <th>卖出日期</th>
                        <th>持股天数</th>
                        <th>买入价</th>
                        <th>卖出价</th>
                        <th>收益率</th>
                        <th>盈亏金额</th>
                        <th>出场原因</th>
                    </tr>
                </thead>
                <tbody id="tradeRows" class="mono"></tbody>
            </table>
            <div class="pagination">
                <button class="btn-page" id="btnPrev" onclick="prevPage()">上一页</button>
                <span id="pageInfo">第 1 / 1 页</span>
                <button class="btn-page" id="btnNext" onclick="nextPage()">下一页</button>
            </div>
        </div>
    </div>

    <!-- Script Block -->
    <script>
        const rawData = {json.dumps(data, ensure_ascii=False)};
        let activeKey = 'strong_open';
        let currentPage = 1;
        const PAGE_SIZE = 12;
        let currentFilteredTrades = [];

        let chartMain = null;
        let chartDD = null;

        document.addEventListener('DOMContentLoaded', () => {{
            chartMain = echarts.init(document.getElementById('chart-main'));
            chartDD = echarts.init(document.getElementById('chart-dd'));
            renderDashboard();
        }});

        function setStrategy(key) {{
            activeKey = key;
            document.querySelectorAll('.tab-button').forEach((btn, idx) => {{
                if ((key === 'strong_open' && idx === 0) || (key === 'limit_up_hold' && idx === 1)) {{
                    btn.classList.add('active');
                }} else {{
                    btn.classList.remove('active');
                }}
            }});
            renderDashboard();
        }}

        function renderDashboard() {{
            const strat = rawData[activeKey];
            if (!strat) return;
            const st = strat.stats;

            // Metrics
            document.getElementById('m-annual').textContent = (st.annual_return >= 0 ? '+' : '') + (st.annual_return * 100).toFixed(2) + '%';
            document.getElementById('m-total').textContent = '总收益: ' + (st.total_return >= 0 ? '+' : '') + (st.total_return * 100).toFixed(2) + '%';
            document.getElementById('m-pf').textContent = st.profit_factor.toFixed(2);
            document.getElementById('m-equity').textContent = Math.round(st.final_equity).toLocaleString() + ' 元';
            document.getElementById('m-profit').textContent = '净赚 +' + ((st.final_equity - 1000000)/10000).toFixed(2) + ' 万元';
            document.getElementById('m-trades').textContent = st.n_trades + ' 笔';
            document.getElementById('m-win').textContent = '胜率: ' + (st.win_rate * 100).toFixed(2) + '% (高盈亏比盈利)';
            document.getElementById('m-best').textContent = '+' + (st.best * 100).toFixed(2) + '%';
            document.getElementById('m-hold').textContent = '平均持仓: ' + st.avg_holding_days + ' 天';
            document.getElementById('m-sharpe').textContent = st.sharpe.toFixed(2);
            document.getElementById('m-sortino').textContent = 'Sortino: ' + st.sortino.toFixed(2);

            // Parse Curves
            const dates = strat.equity_curve.map(pt => pt.date);
            const equity = strat.equity_curve.map(pt => pt.value);
            const bmBase = strat.benchmark_curve && strat.benchmark_curve.length > 0 ? strat.benchmark_curve[0].value : 3800;
            const bm = strat.benchmark_curve.map(pt => ((pt.value / bmBase) * 1000000).toFixed(2));
            const dd = strat.drawdown_curve.map(pt => (pt.value * 100).toFixed(2));

            // Equity Chart
            if (chartMain) {{
                chartMain.setOption({{
                    backgroundColor: 'transparent',
                    tooltip: {{
                        trigger: 'axis',
                        backgroundColor: 'rgba(18, 26, 43, 0.95)',
                        borderColor: 'rgba(255, 255, 255, 0.1)',
                        textStyle: {{ color: '#fff' }}
                    }},
                    legend: {{
                        data: [activeKey === 'strong_open' ? '竞价弱转强抢筹' : '涨停不破强势整理', '全市场等权基准'],
                        textStyle: {{ color: '#94a3b8' }},
                        top: 0
                    }},
                    grid: {{ left: '4%', right: '3%', top: '10%', bottom: '8%', containLabel: true }},
                    xAxis: {{
                        type: 'category',
                        data: dates,
                        axisLine: {{ lineStyle: {{ color: '#334155' }} }},
                        axisLabel: {{ color: '#94a3b8' }}
                    }},
                    yAxis: {{
                        type: 'value',
                        axisLine: {{ show: false }},
                        splitLine: {{ lineStyle: {{ color: 'rgba(255, 255, 255, 0.05)' }} }},
                        axisLabel: {{
                            color: '#94a3b8',
                            formatter: val => (val / 10000).toFixed(0) + '万'
                        }}
                    }},
                    series: [
                        {{
                            name: activeKey === 'strong_open' ? '竞价弱转强抢筹' : '涨停不破强势整理',
                            type: 'line',
                            data: equity,
                            smooth: true,
                            showSymbol: false,
                            lineStyle: {{ width: 3, color: '#ef4444' }},
                            areaStyle: {{
                                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                                    {{ offset: 0, color: 'rgba(239, 68, 68, 0.35)' }},
                                    {{ offset: 1, color: 'rgba(239, 68, 68, 0.0)' }}
                                ])
                            }}
                        }},
                        {{
                            name: '全市场等权基准',
                            type: 'line',
                            data: bm,
                            smooth: true,
                            showSymbol: false,
                            lineStyle: {{ width: 1.5, color: '#64748b', type: 'dashed' }}
                        }}
                    ]
                }});
            }}

            // Drawdown Chart
            if (chartDD) {{
                chartDD.setOption({{
                    backgroundColor: 'transparent',
                    tooltip: {{
                        trigger: 'axis',
                        backgroundColor: 'rgba(18, 26, 43, 0.95)',
                        borderColor: 'rgba(255, 255, 255, 0.1)',
                        textStyle: {{ color: '#fff' }}
                    }},
                    grid: {{ left: '4%', right: '3%', top: '10%', bottom: '10%', containLabel: true }},
                    xAxis: {{
                        type: 'category',
                        data: dates,
                        axisLine: {{ lineStyle: {{ color: '#334155' }} }},
                        axisLabel: {{ color: '#94a3b8' }}
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
                        data: dd,
                        smooth: true,
                        showSymbol: false,
                        lineStyle: {{ width: 2, color: '#f59e0b' }},
                        areaStyle: {{
                            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                                {{ offset: 0, color: 'rgba(245, 158, 11, 0.0)' }},
                                {{ offset: 1, color: 'rgba(245, 158, 11, 0.35)' }}
                            ])
                        }}
                    }}]
                }});
            }}

            // Refresh Trades
            onFilterChange();
        }}

        function onFilterChange() {{
            const query = document.getElementById('filterInput') ? document.getElementById('filterInput').value.trim().toLowerCase() : '';
            const strat = rawData[activeKey];
            if (!strat || !strat.trades) {{
                currentFilteredTrades = [];
            }} else {{
                currentFilteredTrades = strat.trades.filter(t => 
                    (t.symbol && t.symbol.toLowerCase().includes(query)) || (t.name && t.name.toLowerCase().includes(query))
                );
            }}
            currentPage = 1;
            renderTradesTable();
        }}

        function renderTradesTable() {{
            const tbody = document.getElementById('tradeRows');
            if (!tbody) return;
            tbody.innerHTML = '';
            const start = (currentPage - 1) * PAGE_SIZE;
            const pageData = currentFilteredTrades.slice(start, start + PAGE_SIZE);

            pageData.forEach(t => {{
                const pnl = typeof t.pnl_pct === 'number' ? t.pnl_pct : 0;
                const isWin = pnl >= 0;
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td style="color: var(--accent-purple); font-weight: 600;">${{t.symbol}}</td>
                    <td style="color: #fff; font-weight: 500;">${{t.name || '--'}}</td>
                    <td>${{t.entry_date}}</td>
                    <td>${{t.exit_date}}</td>
                    <td>${{t.duration}}天</td>
                    <td>¥${{Number(t.entry_price).toFixed(2)}}</td>
                    <td>¥${{Number(t.exit_price).toFixed(2)}}</td>
                    <td><span class="badge-pnl ${{isWin ? 'win' : 'loss'}}">${{isWin ? '+' : ''}}${{pnl.toFixed(2)}}%</span></td>
                    <td style="color: ${{isWin ? '#f87171' : '#34d399'}};">${{isWin ? '+' : ''}}¥${{Math.round(t.pnl_amount).toLocaleString()}}</td>
                    <td style="color: var(--text-dim);">${{t.exit_reason}}</td>
                `;
                tbody.appendChild(tr);
            }});

            // Update Pagination
            const totalPages = Math.ceil(currentFilteredTrades.length / PAGE_SIZE) || 1;
            document.getElementById('pageInfo').textContent = `第 ${{currentPage}} / ${{totalPages}} 页 (共 ${{currentFilteredTrades.length}} 笔)`;
            document.getElementById('btnPrev').disabled = currentPage <= 1;
            document.getElementById('btnNext').disabled = currentPage >= totalPages;
        }}

        function prevPage() {{
            if (currentPage > 1) {{
                currentPage--;
                renderTradesTable();
            }}
        }}

        function nextPage() {{
            const totalPages = Math.ceil(currentFilteredTrades.length / PAGE_SIZE) || 1;
            if (currentPage < totalPages) {{
                currentPage++;
                renderTradesTable();
            }}
        }}

        window.addEventListener('resize', () => {{
            if (chartMain) chartMain.resize();
            if (chartDD) chartDD.resize();
        }});
    </script>
</body>
</html>
'''

p1 = Path('/Users/stwenmc/Desktop/漫剧/tickflow-stock-panel/yilida_backtest_report.html')
p2 = Path('/Users/stwenmc/Desktop/漫剧/tickflow-stock-panel/frontend/public/yilida_backtest_report.html')
p1.write_text(html_content, encoding='utf-8')
p2.write_text(html_content, encoding='utf-8')
print("Successfully generated report at:")
print(" 1.", str(p1))
print(" 2.", str(p2))
