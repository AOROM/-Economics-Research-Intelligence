# International journal and working-paper sources

## Active English journal catalog

The preset enables `zufe-economics-finance-2020`, extracted from the foreign-journal tables in *浙江财经大学中外文学术期刊定级管理办法（2020年修订）*:

- 8 economics and finance journals from the foreign `TOP` table;
- all 93 journals in the foreign level-A `ECONOMICS, BUSINESS FINANCE` table;
- 101 unique titles and 101 valid, unique ISSNs in total.

The machine-readable names, ISSNs, tiers, scope, and counts are stored in `research_radar/data/zufe_economics_finance_2020.yaml`. Configuration loading checks the ISSN check digit and rejects duplicate names, IDs, or ISSNs. The original Word document is an input supplied by the user and is not committed to the public repository.

## Crossref retrieval

Each catalog entry expands to a `crossref` source and queries:

```text
https://api.crossref.org/journals/{issn}/works
```

The query selects journal articles and applies two boundaries:

1. `from-index-date` begins 14 days before the source's last successful scan; `until-index-date` is the current scan date. The overlap permits delayed or repeated indexing without duplicate reports because DOI identity is retained in state.
2. `from-pub-date` limits candidates to the preceding 180 days and `until-pub-date` to the current date. This prevents a bulk reindex of old metadata from being treated as current literature.

The date ranges are inclusive. A request selects only the metadata used by the monitor and permits at most 1000 records. A larger result is a coverage failure rather than a silently truncated scan. An empty, valid result is a successful scan with no candidates. The first successful query establishes a baseline; its papers are saved for comparison but omitted from the new-paper report.

Crossref supplies bibliographic metadata deposited by publishers and other trusted sources. It is not the publisher website and does not guarantee an abstract or complete issue coverage. The report records the Crossref query as the visibility source and uses `https://doi.org/{doi}` as the paper link so readers reach the current DOI landing page.

The implementation follows Crossref's official [REST API endpoint documentation](https://www.crossref.org/documentation/retrieve-metadata/rest-api/), [filter definitions](https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-filters/), and [API usage guidance](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/).

## Optional feeds

The generic RSS/Atom adapter still accepts explicit `nber`, `cepr`, `repec`, `ssrn`, or `journal` sources. The feed must be on the named provider's domain; journal feeds must be on the configured host. These feeds are not active in the current preset.

Do not claim complete platform coverage from an RSS snapshot. A working-paper revision and later journal issue should be linked to one `ResearchWork` only when DOI, an explicit publication link, or strong title-and-author evidence supports the relationship.
