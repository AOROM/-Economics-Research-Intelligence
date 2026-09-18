# International journal and working-paper sources

The current executable adapter accepts explicit RSS/Atom feeds. `provider` may be `nber`, `cepr`, `repec`, `ssrn`, or `journal`. The feed must be on the named provider's domain; journal feeds must be on the configured host. CEPR publishes its Discussion Papers feed at <https://cepr.org/rss/discussion-paper>. RePEc's NEP publishes field feeds; choose relevant fields explicitly at <https://ideas.repec.org/n/>.

Do not silently claim complete NBER, SSRN, RePEc, or journal coverage from an RSS snapshot. Some feeds contain only recent items or may omit revisions. Where no verified official feed exists, leave a source unconfigured until a site-specific adapter is tested. A working-paper revision and later journal issue should be linked to one `ResearchWork` when DOI, explicit publication link, or strong title-and-author evidence supports it.

`published_online` from a feed is descriptive metadata. The monitor's new-item decision uses first observation after baseline, so a delayed or revised record can still be surfaced. Record the feed URL and item URL in the report.
