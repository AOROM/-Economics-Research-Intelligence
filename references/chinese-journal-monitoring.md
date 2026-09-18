# Chinese journal official-site monitoring

1. The user's journal list is a strict whitelist. Do not auto-add publisher families or similarly named journals.
2. Save each actual official surface: 网络首发、优先出版、最新一期、当前期 or the site's own wording. Keep exact URLs and article-link rules in the config.
3. Enumerate every item on each configured static page and follow pagination. If a dynamic button or blocked page prevents exhaustion, mark that source failed or partial; do not report zero new papers.
4. Discover work identity from DOI, official article ID, stable official URL, then title plus authors plus journal. CNKI and Wanfang may enrich metadata later but never create a Chinese discovery event.
5. On first successful scan, store the current official set as baseline. Later differences create new-work events. 网络首发 to 正式发表 is a version/status event on the same work.
6. For `priority: critical`, retain and briefly report all new articles, including low topic relevance.

## 当前中文期刊白名单（2026-09-18）

以下 11 本由用户指定，均设为 `critical`。`active` 表示已配置可尝试扫描的官方栏目；`pending` 表示期刊在白名单内，但不会扫描，也不会报告“无新文”。当前环境不能直接访问期刊网站抓取原始 HTML；3 个已配置来源的页面和文章链接路径已通过公开可见的官网页面核对，实际运行连通性和 HTML 结构仍需首次扫描验证。

| 期刊 | 官方入口 | 状态 | 当前依据或待办 |
| --- | --- | --- | --- |
| 经济研究 | [社科院期刊站](https://erj.ajcass.com/) | pending | 核对文章列表和翻页规则。 |
| 管理世界 | [杂志社官网](http://www.mwm.net.cn/) | pending | [期刊正文](https://file.qkhz.net/admin/20230602/a76b60ff63267a2527ae3b398e6b56cc.pdf)列此网址；仅核实到 HTTP，需确认 HTTPS 和文章目录。 |
| 经济学（季刊） | [北京大学国家发展研究院期刊目录](https://nsd.pku.edu.cn/xzyj/cbw/jjxjk/qkml/index.htm) | pending | 需实现期次到论文的两级采集。 |
| 世界经济 | [编辑部网站](https://sjjj.magtech.com.cn/) | active | [网络首发](https://sjjj.magtech.com.cn/CN/online_first)、[当期目录](https://sjjj.magtech.com.cn/CN/current)有可识别的官方文章页链接。 |
| 中国工业经济 | [社科院期刊站](https://ciejournal.ajcass.com/) | pending | 核对当期目录和文章链接规则。 |
| 金融研究 | [期刊网站](https://www.jryj.org.cn/CN/1002-7246/home.shtml) | active | [当期目录](https://www.jryj.org.cn/CN/1002-7246/current.shtml)有文章记录；文章链接规则待首次扫描确认。 |
| 财贸经济 | [杂志社期刊站](https://cmjj.ajcass.com/) | pending | 核对文章列表和翻页规则。 |
| 数量经济技术经济研究 | [编辑部网站](https://www.jqte.net/sljjjsjjyj/ch/index.aspx) | pending | 核对最新目录的文章链接规则。 |
| 经济学动态 | [社科院期刊站](https://jjxdt.ajcass.com/) | pending | 当前访问受限，需核对目录和文章链接。 |
| 经济理论与经济管理 | [人大期刊网站](https://jjll.ruc.edu.cn/) | pending | 核对当前目录入口和文章链接规则。 |
| 财经研究 | [上海财经大学期刊社](https://qks.sufe.edu.cn/J/CJYJ.html/CN) | active | [最新论文页](https://qks.sufe.edu.cn/J/CJYJ.html/CN)提供官方文章详情链接。 |

对 `active` 来源，系统要求至少发现一条符合规则的文章链接；找不到时整个来源记为失败。网站访问受限、跳转到其它域名、分页无法穷尽也会报错。`pending` 来源的状态始终显示在周报覆盖情况中。

Static CSS selectors vary across journals. Add a dedicated adapter when a site needs JavaScript, login, or special request parameters. Test the adapter with saved HTML and a live check before relying on weekly output.
