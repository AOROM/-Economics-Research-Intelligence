# 论文提炼与邮件输出

每次检索后，项目只为相较上次成功扫描新增的论文或明确出版版本变化生成带原文依据的研究卡片，并输出邮件主题、正文和原文链接。首次扫描只建立比较基线，不展示基线论文，也不为其批量提炼。没有新增或出版版本变化的期刊从论文部分跳过；全部目标期刊名称仍在邮件开头完整列出。

## 立即使用

```bash
research-radar --config presets/corporate-finance-firm-boundaries.yaml --workdir .literature-monitor/corporate-finance-firm-boundaries
```

命令默认打印 `.eml` 邮件草稿路径，同一次运行还会保存：

| 文件 | 用途 |
| --- | --- |
| `emails/<时间及批次>.eml` | 标准 MIME 邮件草稿，包含 UTF-8 纯文本及 HTML 正文 |
| `emails/<时间及批次>.html` | 浏览器邮件预览 |
| `emails/<时间及批次>.txt` | 含主题的纯文本邮件，可直接复制 |
| `digests/<时间及批次>.md` | 原有 A–F 研究雷达，供已有工作流兼容使用 |
| `summaries/<论文ID>/<提炼ID>.json` | 提炼历史及完整证据片段 |
| `discovered-and-summarized-papers.csv` | 从状态重建的累计论文表，包含题目、来源期刊、作者和摘要 |
| `weekly-run-status.json` | 最近一次被邮件服务器接受的周批次；不包含邮箱、授权码或论文状态 |
| `state.json` | 论文、出版版本、当前卡片、提炼任务与待导出事件 |

用 `--format html`、`--format text` 或 `--format markdown` 改变终端打印的主输出路径；所有格式仍然保存。Python 接口 `run()` 保留 `(返回码, Markdown 路径)`。

对现有记录补做提炼或重新导出邮件：

```bash
research-radar --config presets/corporate-finance-firm-boundaries.yaml --workdir .literature-monitor/corporate-finance-firm-boundaries --summaries-only --format html
```

该模式使用已保存文献，不访问期刊网站；邮件标注未重新扫描，覆盖记录采用上次成功扫描时间。

## 两种提炼方式

默认 `extractive` 在本地挑选摘要或正文中的研究问题、数据、方法、发现、机制、异质性和限制等原句，保留证据位置。英文材料在这一模式下保留英文原句。关键词只能提供方法或主题线索，不能替代识别有效性的评估。

`model` 模式通过用户配置的 Chat Completions 接口生成中文结构化归纳。接口需接受 `messages`、`response_format: {type: json_object}`、`max_completion_tokens`，并返回 `choices[0].message.content` 中的 JSON 字符串。配置示例：

```yaml
summarization:
  mode: model
  endpoint: https://api.openai.com/v1/chat/completions
  model: 填写你有权限使用且支持上述参数的模型名称
  api_key_env: RESEARCH_RADAR_API_KEY
  max_model_calls: 20
  max_attempts: 3
  max_input_chars: 30000
  max_output_tokens: 4000
  timeout_seconds: 45
```

将密钥写入运行环境的 `RESEARCH_RADAR_API_KEY` 环境变量，配置文件只保存环境变量名称。远程接口必须使用 HTTPS；本机 `localhost`、`127.0.0.1` 或 `::1` 的模型服务可以使用 HTTP 并省略密钥。启用模型模式会把本次选入的论文片段提交给配置的服务。

未配置密钥、服务失败、预算用尽或证据校验失败时，邮件保留原文摘录或相同材料下已接受的归纳，并显示待完成状态。每篇、每组材料与分析配置最多尝试三次，达到上限后使用 `--retry-summaries` 重置未完成任务。缺少密钥不消耗尝试次数。一次运行的调用上限按实际模型请求计数，题录不会因预算限制被丢弃。

## 证据规则

每条事实保存字段、内容、归属、原文引文、段落 ID、来源链接和页码或段落位置。字段包括研究问题、理论框架、数据与样本、变量测量、研究方法、识别假设、冲击与处理/对照组、发现、机制、异质性、贡献和限制。

- 只有标题时生成题录与待补材料提示，不生成研究发现。
- 模型引文必须是所引段落中的连续原文，正文提炼不能用标题作为事实依据。
- 程序检查字段结构、引用位置、数字字面值，并拦截部分显著性与百分点单位冲突。此检查不等于证明整条归纳的语义蕴含关系，也不独立验证论文的因果识别。
- 输出以论文报告为归属；作者贡献陈述与系统建议分开展示。
- 重要无显著结果和适用条件应保留；缺少材料时不推断作者未做某项检验。
- 当前选题关联使用概念、方法与数据词表，展示可解释的匹配线索和下一步核读事项，不声称形成了经过独立验证的研究建议。

## 导入正文

自动检索继续遵守已配置的官方发现来源。当前正文入口是用户提供的 `.txt`、`.md` 或带文字层的 `.pdf`，导入时绑定 `state.json` 中的已有论文 ID 和当前出版版本：

```bash
research-radar --config presets/corporate-finance-firm-boundaries.yaml --workdir .literature-monitor/corporate-finance-firm-boundaries --import-fulltext paper.txt --work-id 论文ID --fulltext-source https://期刊官网/论文页面 --format html
```

`--fulltext-source` 不填时采用已收录论文的官网链接。导入后自动进入已有文献提炼模式，不新建论文记录。请先确认正文与所选论文及版本一致；程序的版本绑定不能替代这一身份核对。

PDF 需要安装可选依赖：

```bash
python -m pip install -e ".[pdf]"
```

PDF 页码对应文件的物理页序。扫描图片需要先进行 OCR；本版本不内置 OCR 或自动识别复杂表格。空白页、无法提取文字的页以及超出输入预算的段落会使范围标为部分正文。长正文优先纳入摘要、结果和结论信号段落；邮件披露实际选入段落数。表格数字若不能可靠还原，不应据此填充结果。

## 邮件设置

```yaml
email:
  subject_prefix: 经济学文献简报
  greeting: 你好，
  signature: 经济学研究雷达
  # from: sender@example.com
  # to: reader@example.com
```

`from`、`to` 可省略。邮件开头按“中文期刊、英文 TOP”列出全部目标，随后只展示本期重点论文、中文期刊更新、英文期刊更新和覆盖缺口；同一工作每封邮件只展示一次。摘要后续补全本身不会把旧论文重新列为本期新文。正文中的外部文本经过 HTML 转义，链接限于 HTTP(S)。普通 `research-radar` 命令只输出草稿，不连接邮箱。

仓库中的 `weekly-mail.yml` 每周一北京时间 09:11 调用 `research-radar-weekly`，并在 11:37、15:17 安排两次幂等补偿。只要本周批次已经被邮件服务器接受，补偿运行就会在检索和发信前退出。该命令从运行环境读取 SMTP 账号、授权码和唯一收件地址，通过 TLS 连接 `smtp.163.com:465`，发送同一批次的纯文本及 HTML 合并邮件。发送前，它把累计表发布到仓库的 `reports/discovered-and-summarized-papers.csv`；邮件服务器确认接收后，再更新 `reports/weekly-run-status.json`。状态文件形成每周成功心跳，避免公开仓库长期没有内容变化时被平台停用计划任务。表格只纳入当前配置中的期刊、与提炼绑定的准确出版版本及含有实质提炼内容的论文。来源没有摘要时，摘要栏使用带明确标记的系统内容概括。敏感值只放在 GitHub Actions Secrets；配置、邮件归档和公开分支均不保存授权码。

若定时运行失败，可用提交信息中的 `[weekly-recovery]` 显式触发同一幂等投递流程。SMTP 明确拒绝按认证、发件人、收件人和邮件内容分类；日志只显示安全的 SMTP 状态码。连接中断仍按结果不确定处理，不自动重复发送。

## 状态与失败恢复

1. 保存检索结果及待导出事件，再执行本期新增论文的提炼，模型故障不会丢失已发现论文。
2. 摘要补全与更正作为材料更新，出版状态或明确版本标记变化才产生出版事件；兼容已有的 0.2 版本指纹。
3. 提炼缓存包含正文内容指纹、论文版本、提炼规则版本、模型及相关参数。常规周检只处理新增或出版版本变化；`--summaries-only` 可明确要求重新整理全部已存记录。
4. 新正文不会覆盖另一出版版本的结论。已有提炼历史保存在独立文件；模型升级失败时保留相同材料下已接受的归纳。
5. 本地草稿与研究地图成功写出后，交互运行清除待导出事件；自动投递运行在 SMTP 服务器确认接收后才清除。发送失败会保留事件。
6. 云端运行把状态与尚未确认投递的邮件放入认证加密快照。每周使用周一日期作为批次键；已确认批次不会再次扫描或发送。发送结果不确定时暂停自动重发。先按加密记录中的 Message-ID 核对邮箱，再通过手动工作流选择 `accepted` 或 `retry`，并填写对应周一日期。

普通命令返回码：`0` 表示本次要求的扫描与提炼完成；`1` 全部扫描失败；`2` 部分扫描失败；`3` 配置、状态或文件错误；`4` 扫描完成或使用已有记录，但模型提炼仍有排队、配置或核验任务。扫描错误码优先于 `4`。每周投递命令会把来源缺口写入邮件并保持任务成功；投递失败返回 `5`，加密状态失败返回 `6`，累计表发布失败返回 `7`。

## 接口依据与后续范围

模型接口依据 [Chat Completions 官方说明](https://developers.openai.com/api/reference/resources/chat)。邮件使用 Python 标准库的 [EmailMessage 与 multipart/alternative](https://docs.python.org/3/library/email.examples.html)。PDF 读取及其文本提取边界见 [pypdf 文档](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)。

跨论文结论比较、自动获取全文、OCR、复杂表格提取以及人工批注合并仍属后续功能。它们不作为当前邮件所含分析的已完成能力。
