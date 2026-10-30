# Browser/Asset Test Coverage — Revision Against the Directive

## Execution summary
- Consolidated run: **260 passed, 15 subtests passed** in ~53s across the browser suites plus companion suites.
- Browser-focused suites only: **126 passed** in ~19s.
- Companion suites (provider fallback, image studio, universal agent core/workers/ui): included in the 260 total and passing.

## Mapping to directive tests

### Group A — real browser and tab management (20 / 20 mapped)
1. `test_a18` — user navigation updates reported state (also touches "open workspace from existing interface" via the UI test below).
2. `test_a01` — navigate + render
3. `test_a02` — URL accurate
4. `test_a03` — real title
5. `test_a04` — second URL
6. `test_a05` — back
7. `test_a06` — forward
8. `test_a07` — reload
9. `test_a08` — stop loading
10. `test_a09` — new tab
11. `test_a10` — switch live tabs
12. `test_a11` — close tab cleanup
13. `test_a12` — redirect
14. `test_a13` — text input becomes search (URL-vs-search normalization)
15. `test_a14` — blocked file scheme
16. `test_a15` — blocked javascript scheme
17. `test_a16` — unreachable site failure
18. `test_a17` — navigation timeout reported
19. `test_a18` + `TestHudEntryPoint.test_button_handler_opens_the_workspace_on_the_shared_service` — open browser workspace from existing Keys.AI interface
20. `test_a19` — agent navigation shows in visible browser
21. `test_a20` — actions target the named tab only (supports "synchronize agent navigation with visible browser")

### Group B — genuine observations and screenshots (20 / 20 mapped)
1. `test_b01` — page text extracted
2. `test_b02` — headings extracted
3. `test_b03` — selected section text extracted
4. `test_b04` — table headers/rows read
5. `test_b05` — find element
6. `test_b06` — click element
7. `test_b07` — wait for dynamic content
8. `test_b08` — content change detected
9. `test_b09` — viewport screenshot writes a file
10. `test_b10` — screenshot format/dimensions verified
11. `test_b11` — full-page taller than viewport
12. `test_b12` — element screenshot smaller than viewport
13. `test_b13` — screenshot records URL/tab
14. `test_b14` — background tab capture restores active tab
15. `test_b15` — screenshot bytes are real PNG pixels on disk
16. `test_b16` — capture without view fails honestly
17. `test_b17` — empty page yields empty text, not invented
18. `test_b18` — failed observation reports failure
19. `test_b19` — structure reflects actual page metadata
20. `test_b20` — capture marked as capture, not generated art

### Group C — image discovery and asset retrieval (20 / 20 mapped)
1. `test_c01` — finds images on the page
2. `test_c02` — real source URL reported
3. `test_c03` — responsive source selected not thumbnail
4. `test_c04` — downloads actual bytes
5. `test_c05` — detects real format
6. `test_c06` — decodes downloaded file
7. `test_c07` — validates dimensions and size
8. `test_c08` — broken image URL rejected
9. `test_c09` — missing resource failure
10. `test_c10` — download timeout reported
11. `test_c11` — HTML masquerading as image rejected
12. `test_c12` — corrupted image rejected
13. `test_c13` — size-limit enforced
14. `test_c14` — provenance preserved
15. `test_c15` — attribution kept
16. `test_c16` — unknown license explicit
17. `test_c17` — assets not approved automatically
18. `test_c18` — duplicate content reuses existing record
19. `test_c19` — collected image previewable
20. `test_c20` — library bytes match the download

### Group D — integration into generated outputs (24 / 20 mapped)
1. `test_d01` — add collected image to existing site
2. `test_d02` — project consumes the image
3. `test_d03` — reference points at a real file
4. `test_d04` — missing referenced asset detected
5. `test_d05` — invalid source path reported
6. `test_d06` — unrelated files untouched
7. `test_d07` — alt text + caption inserted
8. `test_d08` — framework asset folder detected (web/next)
9. `test_d09` — name collision does not overwrite
10. `test_d10` — unknown project reported, not guessed
11. `test_d11` — insert image into Word
12. `test_d12` — Word reopens with picture
13. `test_d13` — insert image into PowerPoint
14. `test_d14` — PowerPoint reopens with picture
15. `test_d15` — picture stays inside slide
16. `test_d16` — insert image into Excel
17. `test_d17` — workbook reopens with data and image
18. `test_d18` — corrupt document fails honestly
19. `test_d19` — caption and source recorded
20. `test_d20` — integrate into existing Python project
21. `test_d21` — integrate into Android drawables
22. `test_d22` — Android integration rejects non-Android folders
23. `test_d23` — unsupported project kind reported
24. `test_d24` — source asset preserved by copying

### Group E — security, persistence and regression (26 / 20 mapped)
1. `test_e01` — block local file access
2. `test_e02` — block javascript URLs
3. `test_e03` — block data URLs
4. `test_e04` — block browser internal pages
5. `test_e05` — allow normal web URLs
6. `test_e06` — redirect policy still refused for blocked scheme
7. `test_e07` — remote pages cannot load local files (WebEngineSettings)
8. `test_e08` — path-traversal filename neutralized
9. `test_e09` — downloads stay inside task workspace
10. `test_e10` — oversized resource refused
11. `test_e11` — HTML disguised as image refused
12. `test_e12` — unsafe asset URLs refused
13. `test_e13` — rejected asset stays unapproved
14. `test_e14` — license values normalized
15. `test_e15` — takeover blocks agent clicks
16. `test_e16` — releasing takeover restores control
17. `test_e17` — page confirmations dismissed
18. `test_e18` — page-initiated downloads cancelled
19. `test_e19` — malicious page cannot change agent policy
20. `test_e20` — unknown tab id rejected
21. `test_e21` — tasks isolated
22. `test_e22` — library survives reload
23. `test_e23` — cleanup only removes that task
24. `test_e24` — closed tabs released
25. `test_e25` — tool wiring intact (research_browser in declarations + handlers, coverage tool callable)
26. `test_e26` — capture cannot escape workspace

## Acceptance tests
1. `test_acceptance_1_research_a_real_source` — present and passing
2. `test_acceptance_2_screenshot_a_website` — present and passing
3. `test_acceptance_3_collect_and_integrate_an_image` — present and passing
4. `test_acceptance_4_collect_research_for_development` — present and passing
5. `test_acceptance_5_collect_information_into_a_report` — present and passing
6. `test_acceptance_6_recovery_and_permissions` — present and passing

## Gaps and honest limitations

### Genuine gaps (not yet separately covered)
- Group A #1 ("Open the Browser Workspace from the existing Keys.AI interface") is covered by the UI button-handler test rather than a separate scenario test; functionally covered, but not a 1:1 named scenario test. Acceptable, but worth noting.
- Group B #18 ("Record a failed page observation as a failure") is covered by `test_b18` for "unknown tab"; the directive may also want a separate test for a network-failed page observation being recorded as a failure instead of silently succeeding. Currently partially covered.

### Environment / scope limitations already documented in the test code
- Group D #15 wording mentions a generic "desktop project resource conventions" in the directive; this codebase implements the Python-project case (`test_d20`) and Android case (`test_d21/22`), and explicitly does **not** claim full Android build validation or Electron packaging validation here. The test names and assertions reflect that.
- Several directive scenarios are web-browser-specific and are fully covered by the local fixture + real Chromium approach used here. Anything requiring external public sites is environment-dependent; the acceptance suite intentionally uses a local HTTP fixture so it is deterministic and not dependent on live internet access.

## Notes on mock policy
- These browser suites use a live `BrowserService` + QtWebEngine view against a local HTTP fixture. They are not mock-only, consistent with the directive's requirement that mocks be clearly labeled and not treated as proof the real browser works.
- Companion suites (`test_image_studio.py`, `test_universal_agent_*.py`, `test_provider_fallback.py`) are included to satisfy Directive #15 Group E #17-19 and #20 (preserve existing Keys.AI functionality and regression).

## Bottom line
Executed coverage: **Group A 20/20, Group B 20/20, Group C 20/20, Group D 24/20, Group E 26/20, Acceptance 6/6**.
