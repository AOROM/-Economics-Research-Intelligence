# Chinese journal official-site monitoring

1. The user's journal list is a strict whitelist. Do not auto-add publisher families or similarly named journals.
2. Save each actual official surface: 网络首发、优先出版、最新一期、当前期 or the site's own wording. Keep exact URLs and selectors in the config.
3. Enumerate every item on each configured static page and follow pagination. If a dynamic button or blocked page prevents exhaustion, mark that source failed or partial; do not report zero new papers.
4. Discover work identity from DOI, official article ID, stable official URL, then title plus authors plus journal. CNKI and Wanfang may enrich metadata later but never create a Chinese discovery event.
5. On first successful scan, store the current official set as baseline. Later differences create new-work events. 网络首发 to 正式发表 is a version/status event on the same work.
6. For `priority: critical`, retain and briefly report all new articles, including low topic relevance.

Static CSS selectors vary across journals. Add a dedicated adapter when a site needs JavaScript, login, or special request parameters. Test the adapter with saved HTML and a live check before relying on weekly output.
