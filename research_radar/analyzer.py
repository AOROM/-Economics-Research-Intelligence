"""Conservative, source-grounded economics field extraction and relevance."""

from __future__ import annotations

import re
from importlib.resources import files

import yaml

from .normalize import text_key


METHODS = {
    "Staggered DID": [r"staggered\s+(?:difference[- ]in[- ]differences|did)", r"多期双重差分", r"错位实施.*双重差分"],
    "Triple Difference": [r"triple\s+differences?", r"三重差分", r"\bDDD\b"],
    "Event Study": [r"event[- ]study", r"事件研究法?"],
    "DID": [r"difference[- ]in[- ]differences", r"双重差分", r"(?-i:\bDID\b)"],
    "Shift-share IV": [r"shift[- ]share", r"\bBartik\b", r"份额.*工具变量"],
    "IV": [r"instrumental\s+variables?", r"工具变量", r"\b2SLS\b"],
    "RDD": [r"regression\s+discontinuity", r"断点回归", r"\bRDD\b"],
    "RCT": [r"randomi[sz]ed\s+controlled\s+trial", r"随机对照实验", r"\bRCT\b"],
    "Synthetic Control": [r"synthetic\s+control", r"合成控制"],
    "Panel FE": [r"panel\s+fixed\s+effects?", r"面板固定效应"],
    "Structural Estimation": [r"structural\s+estimation", r"结构估计"],
    "Network Analysis": [r"network\s+analysis", r"网络分析"],
    "Text-as-Data": [r"text[- ]as[- ]data", r"文本分析"],
    "Machine Learning": [r"machine\s+learning", r"机器学习"],
}
DATASETS = ["CSMAR", "CNRDS", "WIND", "RESSET", "CHFS", "CFPS", "CGSS", "CLDS", "Compustat", "CRSP", "Dealscan", "Capital IQ", "Orbis", "Refinitiv", "FactSet", "Census", "BEA", "BLS", "WRDS", "中国工业企业数据库", "中国海关数据库", "上市公司年报"]


def _data(name: str) -> dict:
    return yaml.safe_load((files("research_radar") / "data" / name).read_text(encoding="utf-8"))


def _sentences(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[。！？.!?])\s+|(?<=[。！？])", value) if part.strip()]


def _first_sentence(value: str, patterns: list[str]) -> str | None:
    for sentence in _sentences(value):
        if any(re.search(pattern, sentence, re.I) for pattern in patterns):
            return sentence[:600]
    return None


def analyze(observation: dict, topic: dict) -> dict:
    title = observation.get("title") or ""
    abstract = observation.get("abstract") or ""
    body = title + "\n" + abstract
    key = text_key(body)
    concepts = _data("concepts.yaml")
    china = _data("china.yaml")
    matched = {}
    for concept_id, aliases in concepts.items():
        hits = [alias for alias in aliases.get("zh", []) + aliases.get("en", []) if text_key(alias) and text_key(alias) in key]
        if hits:
            matched[concept_id] = hits
    methods = {name: [pattern for pattern in patterns if re.search(pattern, body, re.I)] for name, patterns in METHODS.items()}
    methods = {name: hits for name, hits in methods.items() if hits}
    if "Staggered DID" in methods or "Triple Difference" in methods:
        methods.pop("DID", None)
    datasets = [name for name in DATASETS if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", body, re.I)]
    china_context = {group: [term for term in terms if term in body] for group, terms in china.items()}
    china_context = {group: terms for group, terms in china_context.items() if terms}
    policy_shock = {
        "named_policy": china_context.get("policy", []),
        "treatment_excerpt": _first_sentence(abstract, [r"\btreatment\s+group\b", r"处理组", r"试点(?:地区|企业|城市)"]),
        "control_excerpt": _first_sentence(abstract, [r"\bcontrol\s+group\b", r"对照组", r"非试点(?:地区|企业|城市)"]),
    }
    jel_explicit = re.search(r"JEL\s*(?:codes?|classification)?\s*[:：]\s*((?:[A-Z]\d{2}[,;\s]*)+)", body, re.I)
    jel = sorted(set(re.findall(r"\b[A-Z]\d{2}\b", jel_explicit.group(1).upper()))) if jel_explicit else []
    period = re.search(r"(?<!\d)(?:19|20)\d{2}\s*[-–—至]\s*(?:19|20)\d{2}(?!\d)", abstract)
    unit = re.search(r"\b(?:firm|bank|county|city|country|individual|household)[- ](?:year|month|quarter)\b|企业[-—]年|公司[-—]年", abstract, re.I)
    design = {
        "research_question": _first_sentence(abstract, [r"\b(?:we|this paper|this study)\s+(?:study|examine|investigate|ask|analy[sz]e)\b", r"本文(?:研究|考察|探讨|分析)"]),
        "economic_mechanism": _first_sentence(abstract, [r"\bmechanism\b", r"\bthrough\b", r"机制", r"渠道"]),
        "theoretical_framework": None,
        "data": datasets,
        "sample": _first_sentence(abstract, [r"\bsample\b", r"样本"]),
        "unit_of_observation": unit.group(0) if unit else None,
        "country_or_region": None,
        "sample_period": period.group(0) if period else None,
        "identification_strategy": list(methods),
        "treatment_or_shock": _first_sentence(abstract, [r"\b(?:policy|exogenous|shock|treatment)\b", r"政策", r"冲击", r"试点"]),
        "main_x": None, "main_y": None,
        "mechanism_tests": _first_sentence(abstract, [r"mechanism\s+test", r"机制检验"]),
        "heterogeneity": _first_sentence(abstract, [r"heterogene", r"异质性"]),
        "main_findings": _first_sentence(abstract, [r"\bwe\s+(?:find|show)\b", r"\bresults?\s+(?:show|suggest)\b", r"结果(?:表明|显示)", r"研究发现"]),
        "contribution": _first_sentence(abstract, [r"\bcontribut", r"边际贡献", r"本文贡献"]),
    }
    topic_key = text_key(topic.get("statement", ""))
    topic_concepts = {cid for cid, aliases in concepts.items() if any(text_key(alias) in topic_key for alias in aliases.get("zh", []) + aliases.get("en", []))}
    shared = topic_concepts.intersection(matched)
    user_terms = [term for term in topic.get("include_concepts", []) if text_key(term) in key]
    topic_score = min(3, len(shared) + len(user_terms) + (1 if text_key(topic.get("statement", "")) in key and topic_key else 0))
    preferred_methods = {text_key(x) for x in topic.get("preferred_methods", [])}
    preferred_data = {text_key(x) for x in topic.get("preferred_datasets", [])}
    method_score = min(3, sum(text_key(x) in preferred_methods for x in methods))
    data_score = min(3, sum(text_key(x) in preferred_data for x in datasets))
    mechanism_score = min(3, len(shared))
    return {
        "concepts": matched, "china_context": china_context, "policy_shock": policy_shock, "jel_codes": jel,
        "methods": list(methods), "datasets": datasets, "design": design,
        "relevance": {"topic": topic_score, "method": method_score, "data": data_score, "mechanism": mechanism_score},
        "evidence_source": observation.get("official_url"),
        "evidence_scope": "title-and-abstract" if abstract else "title-only",
    }
