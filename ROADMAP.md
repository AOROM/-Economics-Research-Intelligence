# V2 implementation status

The V2 architecture is a direction for staged development. This repository contains a usable first release; the table distinguishes shipped behavior from work that needs source-specific evidence or adapters.

| V2 area | Status |
| --- | --- |
| ResearchWork, stable identity, version events, first-seen state | Implemented with offline tests. |
| Strict Chinese official-site whitelist and source adapters | All 11 user-selected journals are recorded. Ten have source-specific official-site adapters; eight passed live collection on 2026-09-19. Management World remains blocked by its unavailable official site. |
| Early release to formal issue deduplication | Implemented for DOI, stable identity, and strong title/author match; ambiguous cases are held for review. |
| Bilingual concepts, JEL, method/data/policy signal extraction | Seed ontology and conservative extraction implemented. Version-bound user-provided text/PDF import is available; automatic full-text retrieval and OCR remain planned. |
| Evidence-linked paper summaries and email | Implemented in 0.3: offline excerpts, optional model Chinese summaries, source/number checks, cached history, retries, and UTF-8 MIME/HTML/plain-text email drafts. Semantic entailment and causal validity still require reading the evidence. |
| NBER, CEPR, RePEc, SSRN and English journal adapters | General official RSS/Atom adapter implemented; CEPR preset verified from its official feed list. Other feed URLs require verification or dedicated adapters. |
| Weekly radar, coverage status, method/data trends, research map | Implemented; scheduling comes from the host. |
| Author watchlist, citation network, research gap detection | Planned. Requires reliable author identities, citations, and explicit evidence standards before release. |

Next priorities: recheck the expired World Economy certificate, the JQTE 502 response, and the unavailable Management World site without weakening TLS or the official-site-only rule. Add NBER official metadata adapter and source-specific version markers; measure coverage against hand-checked weekly snapshots; add stronger source-text extraction for treatment/control and mechanisms.
