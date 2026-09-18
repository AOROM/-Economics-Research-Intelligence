"""Chinese-first, evidence-linked weekly research radar."""

from __future__ import annotations

from collections import Counter


DESIGN_LABELS = {
    "research_question": "研究问题", "economic_mechanism": "经济机制", "theoretical_framework": "理论框架",
    "data": "数据", "sample": "样本", "unit_of_observation": "观察单位",
    "country_or_region": "国家或地区", "sample_period": "样本期",
    "identification_strategy": "识别策略", "treatment_or_shock": "政策或外生冲击",
    "main_x": "核心解释变量", "main_y": "核心结果变量", "mechanism_tests": "机制检验",
    "heterogeneity": "异质性", "main_findings": "核心结果", "contribution": "贡献",
}


def _score(change: dict) -> int:
    return sum((change["work"].get("analysis") or {}).get("relevance", {}).values())


def _detail(change: dict, full: bool = True) -> str:
    work, event = change["work"], change["event"]
    analysis = work.get("analysis") or {}
    lines = [f"### {work['title']}",
             f"- 事件：{'🆕 新工作' if change.get('change_type') == 'new' else '🔄 版本或出版状态更新'}",
             f"- 作者：{', '.join(work.get('authors') or []) or '来源未提供'}",
             f"- 来源：{event['source_name']}；状态：{event.get('status') or '未标注'}",
             f"- 首次发现：{work['first_discovered_at']}",
             f"- 官网/原文：[打开记录]({event['official_url']})"]
    if event.get("doi"):
        lines.append(f"- DOI：[{event['doi']}](https://doi.org/{event['doi']})")
    if not full:
        lines.append(f"- 研究线索：{', '.join(analysis.get('concepts', {})) or '标题和摘要中未识别到预设概念'}；方法：{', '.join(analysis.get('methods', [])) or '未核实'}")
        return "\n".join(lines)
    design = analysis.get("design") or {}
    for field, label in DESIGN_LABELS.items():
        value = design.get(field)
        if value:
            lines.append(f"- {label}：{', '.join(value) if isinstance(value, list) else value}")
    lines.append(f"- 相关度（主题/方法/数据/机制）：{'/'.join(str(analysis.get('relevance', {}).get(k, 0)) for k in ('topic', 'method', 'data', 'mechanism'))}")
    lines.append(f"- 分析证据：[文章页]({analysis.get('evidence_source') or event['official_url']})；提取范围：{analysis.get('evidence_scope', 'unknown')}")
    if not event.get("abstract"):
        lines.append("- 信息边界：来源未提供摘要；研究设计字段未核实的部分不作推断。")
    return "\n".join(lines)


def render_digest(config: dict, changes: dict, scans: list, failures: list[dict], observed_at: str, previous: dict) -> str:
    new = changes["new"]
    updated = changes["updated"]
    active = new + updated
    scans_by_id = {scan.source_id: scan for scan in scans}
    lines = ["# 本周经济学研究雷达", "", f"- 扫描时间：{observed_at}",
             f"- 研究方向：{config['topic']['statement']}",
             f"- 新 ResearchWork：{len(new)}；版本或出版状态更新：{len(updated)}；首次基线收录：{len(changes['baseline'])}",
             "", "## 覆盖情况", ""]
    for scan in scans:
        prior = previous.get("source_scans", {}).get(scan.source_id, {})
        lines.append(f"- {scan.source_name}：已扫描 {scan.pages} 页、{len(scan.observations)} 条；范围为 {scan.coverage}；上次成功扫描：{prior.get('last_successful_scan_at') or '首次扫描'}。")
    for failure in failures:
        prior = previous.get("source_scans", {}).get(failure["source_id"], {})
        lines.append(f"- {failure['source_name']}：**覆盖不完整**；{failure['error']}；上次成功扫描：{prior.get('last_successful_scan_at') or '从未成功'}。")
    for journal in config.get("chinese_monitor", {}).get("journals", []):
        if journal.get("status") == "pending":
            lines.append(f"- {journal['name']}：**待接入，尚未扫描**；{journal.get('note') or '官网采集规则待核实'}；[期刊页面]({journal['homepage']})。")
    if not scans:
        lines.append("- 本次没有可用的一手发现来源，不能据此判断没有新论文。")
    lines += ["", "## A. 与当前研究最相关的新论文", ""]
    relevant = sorted([c for c in active if _score(c) >= 2], key=_score, reverse=True)
    lines.extend([_detail(c) + "\n" for c in relevant] or ["本次已验证的新记录中没有达到当前主题阈值的论文。"])
    lines += ["", "## B. 重点中文期刊官网更新", ""]
    critical_names = [j["name"] for j in config.get("chinese_monitor", {}).get("journals", []) if j.get("priority") == "critical"]
    if critical_names:
        lines += ["| 期刊 | 新论文 | 高相关 | 状态变化 |", "| --- | ---: | ---: | ---: |"]
        for name in critical_names:
            if "zh:" + name not in scans_by_id:
                lines.append(f"| {name} | 未核实 | 未核实 | 未核实 |")
                continue
            cnew = [c for c in new if c["event"]["source_name"] == name]
            cup = [c for c in updated if c["event"]["source_name"] == name]
            lines.append(f"| {name} | {len(cnew)} | {sum(_score(c) >= 2 for c in cnew)} | {len(cup)} |")
        lower = [c for c in active if c["event"]["source_name"] in critical_names and _score(c) < 2]
        if lower:
            lines += ["", "### 其他新增与状态变化", ""]
            lines.extend([_detail(c, full=False) + "\n" for c in lower])
    else:
        lines.append("尚未配置重点中文期刊；中文监控不会自动扩展期刊名单。")
    lines += ["", "## C. 英文 Working Papers", ""]
    papers = [c for c in active if c["event"]["kind"] == "working_paper"]
    lines.extend([_detail(c, full=False) + "\n" for c in papers] or ["本次没有新的或修订的工作论文。"])
    lines += ["", "## D. 英文期刊新文", ""]
    journals = [c for c in active if c["event"]["kind"] == "english_journal"]
    lines.extend([_detail(c, full=False) + "\n" for c in journals] or ["本次没有新的英文期刊论文。"])
    lines += ["", "## E. 本周研究方法动态", ""]
    method_counts = Counter(method for c in active for method in (c["work"].get("analysis") or {}).get("methods", []))
    lines.extend([f"- {method}：{count} 篇有摘要或标题证据的记录。" for method, count in method_counts.most_common()] or ["现有标题和摘要未提供足以标记方法的信息。"])
    lines += ["", "## F. 对当前研究的增量线索", ""]
    data_counts = Counter(dataset for c in relevant for dataset in (c["work"].get("analysis") or {}).get("datasets", []))
    if data_counts:
        lines.append("- 可进一步核读的数据来源：" + "、".join(f"{name}（{count} 篇）" for name, count in data_counts.most_common()) + "。")
    if relevant:
        lines.append("- 上述论文的机制、变量与识别设计以链接原文为核验入口；未从标题或摘要确认的字段留空。")
    else:
        lines.append("- 本次未形成有来源证据支持的新增研究设计线索。")
    if changes["possible_links"]:
        lines += ["", "## 待核对的论文谱系", "", f"- {len(changes['possible_links'])} 个新记录与已有工作相似，未自动合并；请核对标题、作者和版本关系。"]
    lines += ["", "---", "本报告记录的是本监控首次观察和已核实的来源状态；不把观察时间解释为论文首次公开的精确时刻。", ""]
    return "\n".join(lines)
