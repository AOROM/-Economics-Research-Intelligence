# Retrieval and report protocol

1. Load the fixed config and previous state. Freeze one scan timestamp in the configured timezone.
2. Scan every configured Chinese official surface and each configured international feed independently. Reject redirects and links that leave an official host. Preserve each source's prior successful scan time if it fails.
3. Enumerate static pagination until exhausted. A pagination limit, dynamic control, login barrier, or parse failure is a coverage problem; report it explicitly.
4. Normalize DOI, source identity, official URL, and title/author evidence. Store all observed works, even if currently low relevance, so first-seen tracking stays coherent.
5. Save discoveries and pending report events atomically before any model call. Build reading cards from the available abstract or version-bound user-provided full text. Every claim needs source passages; title-only records cannot support findings. See `paper-summaries.md`.
6. Write UTF-8 MIME email drafts, HTML previews, plain-text mail, the compatible A–F digest and research map. Clear pending events after successful export. Failed summaries retain a usable extraction and retry state; a failed source never gets a new successful-scan timestamp.
7. The first successful scan of each source establishes its baseline. Later scans report new ResearchWorks and changed version/status events. Never interpret the monitor's first-seen time as exact first public availability.

This is a research-awareness tool. A systematic review still needs a separately documented search strategy, source coverage, screening procedure, and reproducibility record.
