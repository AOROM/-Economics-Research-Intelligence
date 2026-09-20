"""Render the same research briefing as plain text, HTML and an unsent MIME draft."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from html import escape
from pathlib import Path

from .config import journal_target_groups
from .normalize import url_key
from .summaries import FIELD_LABELS, SCOPE_LABELS, TYPE_LABELS


@dataclass
class MailReport:
    subject: str
    text: str
    html: str


def _link(url: str, label: str) -> str:
    return f'<a href="{escape(url, quote=True)}" style="color:#17598b">{escape(label)}</a>' if url_key(url) else escape(label)


def _card(work: dict, event: dict, change_type: str, detailed: bool) -> tuple[str, str]:
    labels = {"new": "新增论文", "updated": "出版状态或版本更新", "baseline": "首次基线收录",
              "enriched": "来源材料补充", "summary_updated": "提炼或选题关联更新"}
    title = event.get("title") or work["title"]
    source = event["source_name"] + (f"（{event['tier']}）" if event.get("tier") else "")
    author = "、".join(event.get("authors") or work.get("authors") or []) or "来源未提供"
    info = f"{author}｜{source}｜{labels.get(change_type, change_type)}"
    plain = [title, info, "原文：" + event["official_url"]]
    html = [f'<h3 style="font-size:18px;margin:0 0 8px">{_link(event["official_url"], title)}</h3>',
            f'<p style="color:#596575;margin:0 0 10px">{escape(info)}</p>']
    dates = f"出版状态：{event.get('status') or '来源未标注'}；官网日期：{event.get('published_online') or event.get('version_date') or '来源未提供'}；首次收录：{work['first_discovered_at'][:10]}"
    plain.append(dates)
    html.append(f'<p style="font-size:12px;color:#687585">{escape(dates)}</p>')
    if event.get("doi"):
        doi_url = "https://doi.org/" + event["doi"]
        plain.append("DOI：" + doi_url)
        html.append(f'<p style="font-size:12px">DOI：{_link(doi_url, event["doi"])}</p>')
    summary = work.get("summary") or {}
    # Never display a previous paper version's findings under a newer event.
    if summary.get("version_fingerprint") != event["fingerprint"]:
        summary = {}
    mode = "中文归纳" if summary.get("method") == "model" else "原文摘录"
    scope = SCOPE_LABELS.get(summary.get("scope"), "待提炼")
    material = f"材料范围：{scope}；提炼方式：{mode}"
    if summary.get("paper_type", "unknown") != "unknown":
        material += "；文本识别类型：" + TYPE_LABELS[summary["paper_type"]]
    plain.append(material)
    html.append(f'<p style="font-size:12px;color:#687585">{escape(material)}</p>')
    claims = summary.get("claims") or []
    if not claims:
        note = "当前没有足够正文或摘要可供提炼；研究发现、数据和识别策略待原文核实。"
        plain.append(note)
        html.append(f"<p>{escape(note)}</p>")
    evidence = []
    seen_text = set()
    simple = {"overview", "findings", "data_sample", "identification", "limitations"}
    for claim in claims:
        if any(claim["text"] in shown for shown in seen_text) or (not detailed and claim["field"] not in simple):
            continue
        seen_text.add(claim["text"])
        citations = []
        for item in claim["evidence"]:
            if item not in evidence:
                evidence.append(item)
            citations.append((evidence.index(item) + 1, item["url"]))
        refs = "".join(f"[{n}]" for n, _ in citations)
        fields = [c["field"] for c in claims if c["text"] == claim["text"] and (detailed or c["field"] in simple)]
        label = " / ".join(dict.fromkeys(FIELD_LABELS[f] for f in fields))
        plain.append(f"{label}：{claim['text']} {refs}")
        links = " ".join(_link(url, f"[{n}]") for n, url in citations)
        html.append(f'<p style="margin:9px 0"><strong>{escape(label)}：</strong>{escape(claim["text"])} <sup>{links}</sup></p>')
    relevance = work.get("reading_relevance") or {}
    if relevance.get("reasons"):
        reason = "；".join(relevance["reasons"])
        plain.append("选题关联线索：" + reason)
        html.append(f'<p><strong>选题关联线索：</strong>{escape(reason)}</p>')
    if relevance.get("suggestions"):
        suggestions = " ".join(relevance["suggestions"])
        plain.append("建议核读（系统建议）：" + suggestions)
        html.append(f'<p style="background:#f1f6fa;padding:10px"><strong>建议核读：</strong>{escape(suggestions)} <span style="color:#687585">（系统建议）</span></p>')
    for note in summary.get("notes", []):
        plain.append(note)
        html.append(f'<p style="font-size:12px;color:#687585">{escape(note)}</p>')
    job = work.get("summary_job", {})
    if job.get("status") not in {None, "ready"}:
        status = {"pending": "模型提炼已排队", "retry": "模型提炼待重试", "needs_review": "模型提炼待检查",
                  "awaiting_configuration": "等待模型配置"}.get(job["status"], "提炼待完成")
        plain.append("提炼状态：" + status)
        html.append(f'<p style="font-size:12px;color:#8b5a13">{escape(status)}；当前展示可用的有来源版本。</p>')
    if evidence:
        plain.append("原文依据（用于定位，不代表独立复核了作者结论）：")
        html.append('<p style="font-size:12px;color:#687585;margin-bottom:4px">原文依据 · 结论按论文报告呈现</p><ol style="font-size:12px;color:#687585;padding-left:20px">')
        for n, item in enumerate(evidence, 1):
            # The complete passage remains in the structured reading card.
            quote = item["quote"] if len(item["quote"]) <= 200 else item["quote"][:200] + "…"
            plain.append(f"[{n}] {item['location']}：“{quote}” {item['url']}")
            html.append(f'<li>{_link(item["url"], item["location"])}：{escape(quote)}</li>')
        html.append("</ol>")
    return "\n".join(plain), '<div style="border:1px solid #dce4ec;border-radius:8px;padding:18px;margin:16px 0">' + "\n".join(html) + "</div>"


def render_mail(config: dict, state: dict, changes: dict, scans: list, failures: list[dict],
                now: str, summary_result: dict, *, summaries_only: bool = False) -> MailReport:
    email = config.get("email", {})
    counts = {kind: len({c["work_id"] for c in changes.get(kind, [])}) for kind in ("new", "updated", "baseline")}
    date = now[:10]
    subject = f"{email.get('subject_prefix', '经济学文献简报')}｜{date}｜新增 {counts['new']} 篇"
    if summaries_only:
        subject = f"{email.get('subject_prefix', '经济学文献简报')}｜{date}｜已收录文献提炼"
    elif failures:
        subject += " · 部分来源未完成"
    greeting = email.get("greeting", "你好，")
    intro = f"以下是本次文献简报。关注方向：{config['topic']['statement']}。"
    overview = f"新增论文 {counts['new']} 篇；出版状态或版本更新 {counts['updated']} 篇；建立比较基线 {counts['baseline']} 条。基线记录不作为本期新文展示。"
    plain = ["主题：" + subject, "", greeting, "", intro, overview]
    html = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
            f'<title>{escape(subject)}</title></head><body style="margin:0;background:#f4f6f8;color:#233041;font-family:Arial,\'Microsoft YaHei\',sans-serif;line-height:1.75">',
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center" style="padding:24px 12px"><table role="presentation" width="720" cellspacing="0" cellpadding="0" style="width:100%;max-width:720px;background:#fff"><tr><td style="padding:28px">',
            '<p style="font-size:12px;color:#587188;letter-spacing:2px">ECONOMICS RESEARCH INTELLIGENCE</p>',
            f'<h1 style="font-size:24px;line-height:1.4">{escape(subject)}</h1><p>{escape(greeting)}</p><p>{escape(intro)}</p><p>{escape(overview)}</p>']
    target_groups = journal_target_groups(config)
    target_count = sum(len(names) for _, names in target_groups)
    plain += ["", f"本次检索期刊名单（{target_count} 本，含明确标注的未完成项）", ""]
    html.append(f'<h2 style="font-size:20px;border-bottom:2px solid #dce4ec;padding-bottom:8px">本次检索期刊名单（{target_count} 本，含明确标注的未完成项）</h2>')
    for label, names in target_groups:
        plain.append(f"{label}（{len(names)} 本）：" + "；".join(names))
        html.append(f'<h3 style="font-size:16px;margin-bottom:4px">{escape(label)}（{len(names)} 本）</h3><ol style="margin-top:4px;padding-left:24px;columns:2">')
        html.extend(f"<li>{escape(name)}</li>" for name in names)
        html.append("</ol>")
    if summaries_only:
        note = "本次整理已有文献，未重新扫描期刊；以下覆盖信息为上次成功扫描记录。"
        plain.append(note)
        html.append(f'<p style="color:#687585">{escape(note)}</p>')
    groups = {"重点论文": [], "中文期刊其他更新": [], "英文期刊其他更新": [], "英文工作论文更新": []}
    seen = set()
    visible_kinds = ("summary_updated",) if summaries_only else ("new", "updated")
    for kind in visible_kinds:
        for change in changes.get(kind, []):
            work_id = change["work_id"]
            if work_id in seen:
                continue
            seen.add(work_id)
            work = state["works"][work_id]
            event = work["versions"][-1]
            score = sum(work.get("reading_relevance", {}).get("scores", {}).values())
            if score >= 2:
                group = "重点论文"
            elif event["kind"] == "working_paper":
                group = "英文工作论文更新"
            else:
                group = "中文期刊其他更新" if event["kind"] == "chinese_journal" else "英文期刊其他更新"
            groups[group].append((score, work, event, kind))
    for label, cards in groups.items():
        if not cards:
            continue
        plain += ["", label, ""]
        html.append(f'<h2 style="font-size:20px;border-bottom:2px solid #dce4ec;padding-bottom:8px">{escape(label)}</h2>')
        for score, work, event, kind in sorted(cards, key=lambda c: c[0], reverse=True):
            text, markup = _card(work, event, kind, score >= 2 or "full-text" in work.get("summary", {}).get("scope", ""))
            plain += [text, ""]
            html.append(markup)
    if not seen:
        note = "本次没有可列出的新增论文或出版版本变化；没有新文的期刊已从论文部分跳过。"
        plain += ["", note]
        html.append(f"<p>{escape(note)}</p>")
    plain += ["", "来源覆盖", ""]
    html.append('<h2 style="font-size:20px">来源覆盖</h2><ul>')
    coverage = []
    if summaries_only:
        coverage = [f"{row['source_name']}：上次成功扫描 {row['last_successful_scan_at']}，观察到 {row['candidate_count']} 条；范围 {row['coverage']}。"
                    for row in state.get("source_scans", {}).values()]
    else:
        changed_sources = {row["event"]["source_id"] for kind in ("new", "updated") for row in changes.get(kind, [])}
        journal_scans = [scan for scan in scans if scan.kind in {"chinese_journal", "english_journal"}]
        skipped = sum(scan.source_id not in changed_sources for scan in journal_scans)
        coverage = [f"成功完成 {len(scans)} 个来源；其中 {skipped} 本期刊没有新增论文或出版版本变化，已从论文部分跳过。"] if scans else []
        coverage += [f"{f['source_name']}：覆盖不完整；{f['error']}。" for f in failures]
    for journal in config["chinese_monitor"]["journals"]:
        if journal.get("status") in {"pending", "blocked"}:
            status = "待接入，尚未扫描" if journal["status"] == "pending" else "官网外部阻塞，尚未扫描"
            coverage.append(f"{journal['name']}：{status}；{journal.get('note') or '采集规则待核实'}。")
    if not coverage:
        coverage.append("没有可确认的来源覆盖记录。")
    for line in coverage:
        plain.append("- " + line)
        html.append(f"<li>{escape(line)}</li>")
    html.append("</ul>")
    pending = summary_result.get("pending", 0) + summary_result.get("awaiting_configuration", 0)
    failed = summary_result.get("failed", 0)
    if pending or failed:
        note = f"提炼进度：{pending} 篇模型提炼待完成，{failed} 篇达到重试上限待检查；已收录的论文及可用摘录均予保留。"
        plain += ["", note]
        html.append(f"<p>{escape(note)}</p>")
    signature = email.get("signature", "经济学研究雷达")
    ending = f"{signature}\n生成时间：{now}\n材料不足的字段保留待核实；选题关联和建议核读由系统生成。"
    plain += ["", ending, ""]
    html.append(f'<hr style="border:0;border-top:1px solid #dce4ec"><p style="font-size:12px;color:#687585">{escape(ending).replace(chr(10), "<br>")}</p></td></tr></table></td></tr></table></body></html>')
    return MailReport(subject, "\n".join(plain), "\n".join(html))


def write_mail(report: MailReport, directory: Path, stem: str, config: dict, now: str) -> dict[str, Path]:
    message = EmailMessage(policy=policy.SMTP)
    message["Subject"] = report.subject
    message["Date"] = format_datetime(datetime.fromisoformat(now))
    message["Message-ID"] = make_msgid(domain="research-radar.local")
    message["X-Unsent"] = "1"
    for name in ("from", "to"):
        if config.get("email", {}).get(name):
            message[name.title()] = config["email"][name]
    # No SMTP/mail connector is invoked: these are portable draft artifacts.
    message.set_content(report.text, charset="utf-8")
    message.add_alternative(report.html, subtype="html", charset="utf-8")
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for suffix, content in (("txt", report.text.encode("utf-8")), ("html", report.html.encode("utf-8")), ("eml", message.as_bytes())):
        path = directory / f"{stem}.{suffix}"
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_bytes(content)
        temp.replace(path)
        paths[suffix] = path
    return paths
