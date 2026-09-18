# Retrieval and report protocol

1. Load the fixed config and previous state. Freeze one scan timestamp in the configured timezone.
2. Scan every configured Chinese official surface and each configured international feed independently. Reject redirects and links that leave an official host. Preserve each source's prior successful scan time if it fails.
3. Enumerate static pagination until exhausted. A pagination limit, dynamic control, login barrier, or parse failure is a coverage problem; report it explicitly.
4. Normalize DOI, source identity, official URL, and title/author evidence. Store all observed works, even if currently low relevance, so first-seen tracking stays coherent.
5. Analyze title and abstract. Do not invent abstract, sample, mechanism, treatment/control, or contribution fields. For deeper fields, read and cite an accessible authoritative full text.
6. Write the A–F digest, then atomically save updated state and research map. A failed source never gets a new successful-scan timestamp.
7. The first successful scan of each source establishes its baseline. Later scans report new ResearchWorks and changed version/status events. Never interpret the monitor's first-seen time as exact first public availability.

This is a research-awareness tool. A systematic review still needs a separately documented search strategy, source coverage, screening procedure, and reproducibility record.
