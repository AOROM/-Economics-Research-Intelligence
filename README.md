# Economics Research Intelligence

面向经济学、金融学和管理学研究的中英文文献监控项目。它把**用户指定的中文期刊官网**与**明确配置的国际期刊及工作论文订阅源**汇入同一 `ResearchWork` 库，按首次观察记录新工作，追踪可核实的版本变化，并生成带来源链接的中文研究雷达。

## 当前可运行能力

| 能力 | 实现方式 |
| --- | --- |
| 中文官网白名单 | 预设包含用户指定的 11 本期刊。10 本已有官网采集程序：8 本在 2026-09-19 实时验证成功，另 2 本因官网证书或 502 暂时失败；《管理世界》官网持续超时，明确标为外部阻塞。 |
| 英文工作论文和期刊 | RSS/Atom 订阅源适配器；CEPR 官网公布的 Discussion Papers RSS 提供可用预设。NBER、RePEc/NEP、SSRN 和英文期刊需要用户提供已核实的源地址。 |
| ResearchWork 与版本 | DOI、来源稳定 ID、官方 URL 优先；标题和作者高相似度时合并，不确定的谱系留待人工核对。 |
| 首次观察 | 首次成功扫描建立基线；后续扫描把新增工作与出版状态或版本变化分开。所有已发现记录进入状态库，包括低相关记录。 |
| 经济学分析 | 双语概念词表、方法与数据名识别、多维相关度；研究设计字段只提取标题或摘要中有依据的内容。 |
| 交付 | A–F 分层 Markdown 周报、每个来源的覆盖状态、长期 `research_map.json`。 |

中文采集同时支持静态 HTML、AJCASS 官方公开接口和北京大学“期次页面到论文 PDF”的两级结构。扫描失败、证书失效或栏目没有匹配到论文链接时，会显示为覆盖不完整，不会变成“无新文”。`blocked` 期刊会在周报中说明官网阻塞及证据边界。RSS 快照只能代表该订阅源提供的条目，不能证明整个平台已被穷尽。研究设计抽取基于标题和摘要，不能替代全文核读；缺失字段保留为空。

## 快速开始

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
research-radar --config presets/corporate-finance-firm-boundaries.yaml --workdir .literature-monitor/corporate-finance-firm-boundaries
```

首次运行会建立基线。第二次及以后运行才报告新工作与版本变化。周报保存到 `workdir/digests/`，状态和研究地图保存在 `workdir/`。`workdir` 默认不应提交到公开仓库。

返回码：`0` 全部配置来源扫描成功；`2` 部分来源失败；`1` 全部来源失败；`3` 配置或状态错误。失败来源的上次成功扫描时间会保留，周报会点名覆盖缺口。

定时运行由宿主产品的 recurring automation、任务计划程序或 cron 执行本命令。安装此项目本身不会启动后台监控。

## 加入中文期刊

当前 11 本中文期刊及逐刊验证结果见[中文期刊监控说明](references/chinese-journal-monitoring.md)。10 本配置为 `active`；《管理世界》因唯一官网持续超时标为 `blocked`。实时验证已成功取得 8 本期刊的当期记录。《世界经济》官网证书已过期，《数量经济技术经济研究》官网返回 502；两者的解析规则已经配置，但运行会如实报告外部失败。

在配置的 `chinese_monitor.journals` 中**明确**加入期刊名称、首页、允许的官方域名及每个栏目。可以用经核对的 `link_path_regex` 识别官方文章链接，或用页面结构对应的 CSS 选择器。对重点期刊设 `priority: critical`，系统会先保存栏目全部新条目，再做相关度分析；低相关新增文仍在周报 B 节巡视。中文新文不会从 CNKI、万方、搜索引擎或 Crossref 发现。

先对一个期刊用本地样例或少量真实页面验证选择器、分页和官网链接。若“下一页”是动态按钮而没有可见链接，运行会报告覆盖失败，需开发该站专用适配器。

## 加入国际来源

在 `international_monitor.sources` 添加 `provider`（`nber`、`cepr`、`repec`、`ssrn`、`journal`）、`name`、`feed_url`。前四类订阅地址必须在相应机构域名下；`journal` 使用用户明确指定的期刊订阅源。CEPR 的源地址见[官网 RSS 列表](https://cepr.org/rss-feeds)；RePEc 的 NEP 提供按领域订阅源，见[官方说明](https://repec.org/)和[NEP 列表](https://ideas.repec.org/n/)。不为 NBER 或 SSRN 猜测未核实的订阅地址。

## 身份与时间语义

- `first_discovered_at`：本监控第一次在已配置来源观察到该工作；它不是论文真正首次公开的精确时刻。
- `published_online`：来源明确提供时保存，中文新文**不**靠这个日期入选，因此周运行与七日窗口之间不会产生边界漏报。
- `versions`：同一工作在不同工作论文平台、网络首发和正式发表的来源事件。DOI 一致可直接连接；高相似标题和作者可自动连接；较弱匹配保留候选，不强行合并。
- 首次运行只建基线，不把原本就存在的所有历史文章称为“本周新文”。

## 目录

- `research_radar/`：采集、分析、ResearchWork 状态与周报。
- `research_radar/data/`：双语经济概念和中国经济语境词表。
- `presets/`：可编辑的研究方向配置。
- `references/`：来源、识别策略、论文生命周期与报告规范。
- `schemas/`：监控配置和持久状态结构。
- `tests/fixtures/`：不依赖在线网站的回归样例。

本项目按用户的《Literature-monitor-skills 经济学研究监控优化方案 V2.0》实现。原始 [Literature-monitor-skills](https://github.com/l2461090/Literature-monitor-skills) 提供了“官网可见、来源核验”的设计起点；本仓库的代码与配置为独立实现。
