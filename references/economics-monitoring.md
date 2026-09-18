# Economics monitoring contract

The monitoring unit is `ResearchWork`, not a publication-date row. A work can carry multiple `versions` from working-paper platforms, an early journal surface, and a final issue. `first_discovered_at` is the monitor's observation timestamp; `first_public_version_at` and `journal_publication_at` are stored only when an official source supplies an interpretable date.

Chinese and international discovery routes differ. Chinese journals enter only through user-specified official domains and surfaces. International journal and working-paper sources enter through explicit publisher or platform feeds. Neither route may turn a metadata hit into an official discovery event without verifying the configured source.

The common analysis stage records concepts, methods, datasets, research design excerpts, source URLs, and four relevance dimensions: topic, method, data, and mechanism. Priority is a source setting, not a relevance score. Full-text analysis, if later added by an agent, needs a citation to the accessible paper text and must keep uncertain fields empty.
