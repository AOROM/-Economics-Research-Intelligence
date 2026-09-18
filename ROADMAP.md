# V2 implementation status

The V2 architecture is a direction for staged development. This repository contains a usable first release; the table distinguishes shipped behavior from work that needs source-specific evidence or adapters.

| V2 area | Status |
| --- | --- |
| ResearchWork, stable identity, version events, first-seen state | Implemented with offline tests. |
| Strict Chinese official-site whitelist and static-page registry | User's 11 journals are recorded. Three have official page URL patterns configured for scanning; eight are explicitly pending. All require first-run live validation. |
| Early release to formal issue deduplication | Implemented for DOI, stable identity, and strong title/author match; ambiguous cases are held for review. |
| Bilingual concepts, JEL, method/data/policy signal extraction | Seed ontology and conservative title/abstract extraction implemented; full-text detail needs source review. |
| NBER, CEPR, RePEc, SSRN and English journal adapters | General official RSS/Atom adapter implemented; CEPR preset verified from its official feed list. Other feed URLs require verification or dedicated adapters. |
| Weekly radar, coverage status, method/data trends, research map | Implemented; scheduling comes from the host. |
| Author watchlist, citation network, research gap detection | Planned. Requires reliable author identities, citations, and explicit evidence standards before release. |

Next priorities: run a live scan of the three configured Chinese sources, inspect the resulting coverage report, then implement and validate the eight pending journal adapters. Add NBER official metadata adapter and source-specific version markers; measure coverage against hand-checked weekly snapshots; add stronger source-text extraction for treatment/control and mechanisms.
