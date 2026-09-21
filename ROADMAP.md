# V2 implementation status

The V2 architecture is a direction for staged development. This repository contains a usable first release; the table distinguishes shipped behavior from work that needs source-specific evidence or adapters.

| V2 area | Status |
| --- | --- |
| ResearchWork, stable identity, version events, first-seen state | Implemented with offline tests. |
| Strict Chinese official-site whitelist and source adapters | All 11 user-selected journals are recorded. Ten have source-specific official-site adapters; eight passed live collection on 2026-09-19. Management World remains blocked by its unavailable official site. |
| Early release to formal issue deduplication | Implemented for DOI, stable identity, and strong title/author match; ambiguous cases are held for review. |
| Bilingual concepts, JEL, method/data/policy signal extraction | Seed ontology and conservative extraction implemented. Version-bound user-provided text/PDF import is available; automatic full-text retrieval and OCR remain planned. |
| Evidence-linked paper summaries, cumulative table, and email | Implemented in 0.6: offline excerpts, optional model Chinese summaries, source/number checks, cached history, a repository CSV of summarized journal papers, UTF-8 MIME/HTML/plain-text reports, and weekly TLS SMTP delivery with conservative retry handling. Normal scans summarize only new papers or publication-version changes; baseline papers remain silent. Semantic entailment and causal validity still require reading the evidence. |
| Zhejiang University of Finance and Economics English journals | Implemented: the active catalog contains only the 8 economics and finance TOP journals, with checked ISSNs and bounded Crossref journal-work queries. The report begins with all 8 English names alongside the configured Chinese targets. Crossref coverage remains dependent on publisher deposits. |
| NBER, CEPR, RePEc, SSRN and explicit journal feeds | General RSS/Atom adapter remains available but these feeds are not enabled in the current preset. Source-specific adapters require verified URLs and coverage tests before activation. |
| Weekly radar, coverage status, method/data trends, research map | Implemented; included GitHub Actions schedule runs at Monday 09:00 Asia/Shanghai after repository secrets are configured and the enable variable is set. Runtime state is authenticated and encrypted. |
| Author watchlist, citation network, research gap detection | Planned. Requires reliable author identities, citations, and explicit evidence standards before release. |

Next priorities: recheck the expired World Economy certificate, the JQTE 502 response, and the unavailable Management World site without weakening TLS or the official-site-only rule. Measure Crossref coverage against publisher issue pages and hand-checked weekly snapshots; add stronger source-text extraction for treatment/control and mechanisms.
