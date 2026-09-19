# Chinese journal official-site monitoring

1. The user's journal list is a strict whitelist. Do not auto-add publisher families or similarly named journals.
2. Save each actual official surface: 网络首发、优先出版、最新一期、当前期 or the site's own wording. Keep exact URLs and article-link rules in the config.
3. Enumerate every item on each configured static page and follow pagination. If a dynamic button or blocked page prevents exhaustion, mark that source failed or partial; do not report zero new papers.
4. Discover work identity from DOI, official article ID, stable official URL, then title plus authors plus journal. CNKI and Wanfang may enrich metadata later but never create a Chinese discovery event.
5. On first successful scan, store the current official set as baseline. Later differences create new-work events. 网络首发 to 正式发表 is a version/status event on the same work.
6. For `priority: critical`, retain and briefly report all new articles, including low topic relevance.

## 当前中文期刊白名单（2026-09-19）

以下 11 本由用户指定，均设为 `critical`。`active` 表示已有经过页面样本验证的采集程序；一次实时失败仍会显示为覆盖不完整。`blocked` 表示官网入口已核实，但当前无法取得足够内容来建立可信采集规则。系统没有为失败期刊改用 CNKI、万方或搜索结果发现论文。

| 期刊 | 官方入口 | 配置状态 | 2026-09-19 验证结果 |
| --- | --- | --- | --- |
| 经济研究 | [社科院期刊站](https://erj.ajcass.com/) | active / AJCASS API | 成功：11 篇，作者和摘要均取得。 |
| 管理世界 | [杂志社官网](http://www.mwm.net.cn/) | blocked | HTTP 与 HTTPS 均持续超时，无法验证目录结构；不以知网页面替代。 |
| 经济学（季刊） | [北京大学国家发展研究院期刊目录](https://nsd.pku.edu.cn/xzyj/cbw/jjxjk/qkml/index.htm) | active / 两级目录 | 成功：16 篇，取得标题、作者、论文 PDF 和期次发布日期。 |
| 世界经济 | [编辑部网站](https://sjjj.magtech.com.cn/) | active / HTML | 页面样本可识别网络首发 6 篇、当期 8 篇；安全实时请求因官网证书过期而失败。程序不关闭证书验证。 |
| 中国工业经济 | [社科院期刊站](https://ciejournal.ajcass.com/) | active / HTML | 成功：9 篇，取得标题和作者；详情页受官网 WAF 阻断，摘要留空。 |
| 金融研究 | [期刊网站](http://www.jryj.org.cn/CN/1002-7246/home.shtml) | active / HTML | 成功：11 篇，取得标题、作者和摘要。官网 HTTPS 证书域名不匹配，使用其仍可访问的 HTTP 正式页面。 |
| 财贸经济 | [杂志社期刊站](https://cmjj.ajcass.com/) | active / HTML | 成功：10 篇，取得标题、作者和摘要。 |
| 数量经济技术经济研究 | [编辑部网站](https://www.jqte.net/sljjjsjjyj/ch/index.aspx) | active / HTML | 官网路径与文章链接规则已核实；实时请求返回 502，运行会报告覆盖失败。 |
| 经济学动态 | [社科院期刊站](https://jjxdt.ajcass.com/) | active / AJCASS API | 成功：9 篇，作者和摘要均取得。 |
| 经济理论与经济管理 | [人大期刊网站](http://jjll.ruc.edu.cn/CN/1000-596X/current.shtml) | active / HTML | 成功：9 篇，取得标题、作者和摘要。官网当前目录只通过 HTTP 提供。 |
| 财经研究 | [上海财经大学期刊社](https://qks.sufe.edu.cn/J/CJYJ.html/CN) | active / HTML + 详情元数据 | 成功：10 篇，取得标题、作者、摘要、DOI 和日期元数据。 |

对 `active` 来源，系统要求至少发现一条符合规则的文章链接；找不到时整个来源记为失败。网站访问受限、证书失效、跳转到其它域名、分页无法穷尽也会报错。详情页失败时，程序保留已经核实的目录记录，并在覆盖字段中报告元数据缺口。

三类适配器分别处理普通 HTML、AJCASS 公开接口和北大期次页面。站内页面错误输出的 HTTP 链接只在同一主机且栏目本身使用 HTTPS 时自动升级；明确只提供 HTTP 的官网必须逐刊设置 `allow_http: true`。TLS 证书验证保持开启。
