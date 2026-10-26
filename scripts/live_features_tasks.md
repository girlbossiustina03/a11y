# Feature live suite (opt-in)

No live run was performed while implementing this suite. Run only after the owner hands over the screen:

`.venv/bin/python scripts/live_eval.py --suite features --runs 1`

48 cases, 55 turns. `all` remains unchanged. `<digits>` is a fresh per-build marker.

UI cases first ask the arithmetic request shown to produce a reply without a model; the check then applies the System Events stimulus. Every task has an independent real-state check. Successful cases reject computer-control denials and promise-only replies; the deliberately failed first turn permits an honest task failure but never a computer-control denial.

| Name | Request | Check |
|---|---|---|
| retry_calculator_length | In Calculator, show the metric equivalent of a dozen inches, with centimeters as the destination unit. | Calculator AX contains 30.48 and Centimeters. |
| retry_calculator_temperature | Have Calculator display the Celsius equivalent of sixty-eight degrees Fahrenheit. | Calculator AX contains Celsius and 20. |
| retry_clock_world | Bring up Clock’s panel that compares local times around the world. | World Clock is selected in native AX. |
| retry_clock_timer | In Clock, begin a countdown lasting 600 seconds. | AX shows running 10-minute countdown; refuse pre-existing timers; cancel owned timer in finally. |
| retry_calendar_day | Let me see a single day at a time in Calendar. | Day View menu item is checked. |
| retry_calendar_week | Display the seven-day layout in Calendar. | Week View menu item is checked. |
| retry_maps_place | Locate the Eiffel Tower using Apple Maps and leave its place details showing. | Maps foreground; AX contains Eiffel Tower. |
| retry_dictionary_lookup | Use Dictionary to display the entry for serendipity, rather than answering from memory. | Dictionary foreground; AX contains serendipity. |
| retry_safari_find | Use Safari’s page search to highlight illustrative in this webpage. | Exact example.com URL and AX search field equals illustrative. |
| retry_safari_zoom | Increase the magnification of this Safari webpage with the keyboard shortcut. | Exact URL and native link height increases; zoom restored in finally. |
| retry_stocks_business_news | Choose the Business News section of the Stocks sidebar. | Business News is selected, not just visible. |
| retry_font_book_computer | Select Computer in Font Book’s sidebar so its collection is displayed. | Computer collection is selected. |
| retry_activity_cpu_sort | Arrange the CPU table in Activity Monitor with the highest processor usage first. | % CPU AXSortDirection is descending. |
| held_settings_look | Navigate to the Appearance pane; keep the current theme selected. | Appearance pane verified by native pane check. |
| held_finder_nested | Drill down through Recipes to its Saturday subfolder in this test window. | Exact fixture Recipes/Saturday target. |
| held_finder_sort | Show this test directory as a name-sorted list in Finder. | Exact fixture target, list view and Name sort column. |
| held_finder_info | Bring up Get Info for this orchard test directory. | Exact fixture folder Info window exists; explicitly closed. |
| held_finder_read | Read the packing instructions from A11y test <digits> packing.txt in the test directory. | Exact fixture document path, unchanged disk content, and amber lantern in reply. |
| held_web_screen_answer | Load https://example.org/ and quote its main heading to me. | Exact example.org URL, tab title and Example Domain in reply. |
| held_preview_sidebar | Turn on the thumbnail strip in this test PDF, then report the document name. → Read out this PDF’s exact filename while leaving the thumbnail strip visible. | Exact marked PDF; Thumbnails menu checked; follow-up includes exact filename. |
| held_textedit_lines | Enter these exact lines into the saved test document: / A11y test <digits> / Saturday picnic / Bring pears and a blanket. | Exact saved fixture path and full in-memory document text. |
| held_textedit_sentence | Fill the saved test document with exactly: / A11y test <digits> / The spare umbrella is beside the boots. | Exact saved fixture path and full in-memory document text. |
| held_notes_pair | In Notes, save a note named A11y test <digits>, whose complete body is: Bring the green blanket and two pears. → In Notes, save a note named A11y test <digits>, whose complete body is: Leave the basket by the door. | Exactly one matching note per title with complete exact body; per-title finally cleanup. |
| held_reminders_pair | Create a reminder named A11y test <digits> due tomorrow at 08:00. → Create a reminder named A11y test <digits> due tomorrow at 14:00. | Exactly one matching reminder per title with tomorrow 08:00 / 14:00 due dates; per-title finally cleanup. |
| held_lookup_memory | Inspect General, About in System Settings and report the installed RAM capacity in gigabytes. | About pane and reply GB value matches sysctl hw.memsize. |
| held_lookup_dictionary | Find Dictionary’s definition of nocturnal and explain the part about night. | Dictionary foreground, AX/window OCR contains nocturnal/night, reply contains night. |
| held_mascot_corners | Place your own window at the upper left edge of the display, please. → Place your own window at the lower right edge of the display, please. | Actual mascot geometry within 40px of requested corner. |
| held_mascot_edges | Place your own window at the upper right edge of the display, please. → Place your own window at the lower left edge of the display, please. | Actual mascot geometry within 40px of requested corner. |
| follow_restart | Visit the reserved-domains reference at iana.org/domains/reserved in Safari. → Now the same for example.net in that browser. | Exact IANA URL, then task activity and exact example.net URL in same session. |
| retry_after_failure | Enter the Recovered subfolder in this Finder test directory. → You didn't do it; try entering that folder again. | Missing fixture folder produces genuine task failure; create target; follow-up must execute and reach exact target. |
| companion_face | What is 320 plus 17? | System Events click at face; socket input visible and focused. |
| companion_menus | What is 321 plus 17? | Own PID frontmost; System Events reads menu bar groups and all action labels. |
| companion_right_click | What is 322 plus 17? | Control-click at face; no process popup menus; input/reply state unchanged. |
| companion_green | What is 323 plus 17? | AXZoomButton pressed twice; input toggles and returns to original state. |
| companion_yellow | What is 324 plus 17? | AXMinimizeButton pressed; native AXMinimized is true. |
| companion_reply_buttons | What is 325 plus 17? | Reply AXZoomButton disabled; AXMinimizeButton closes reply. |
| companion_spaces | What is 326 plus 17? | Read Spaces count/current ID; switch to neighbor and back in finally; verify changed Space and own on-screen window via CGWindowList; recorded skip when unsafe/unavailable/one Space. |
| fixture_scroll | Scroll down through this Finder list and select 179 A11y test <digits>.txt near the bottom. | Exact bottom fixture selection plus scroll receipt. |
| fixture_drag | Drag 179 A11y test <digits>.txt from Source into its sibling Destination folder; ask me before moving it. | Record pending confirmation and source/destination disk state; needs_owner because move is outside eval confirm allowlist; never auto-confirm. |
| fixture_context | Right-click 179 A11y test <digits>.txt in this fixture folder and choose Get Info from its context menu. | Exact file Info window plus right-click/context receipt. |
| fixture_bold | Select all of the text in the saved A11y test <digits>.rtf fixture and apply bold with the keyboard. | Exact RTF path, full text unchanged, every character font is bold. |
| fixture_cursor | In this Finder fixture, click the Name column, then the Date Modified column, then Name again. | Multiple distinct parked step samples visible throughout interval; painted pointer size within tolerance of system preference; hidden after mascot re-forms. |
| public_scroll_section | Scroll down to section 1 Introduction in this RFC page, and read its section heading aloud. | Exact RFC URL; changed AX scroll position; heading in viewport OCR and reply; scroll receipt. |
| public_scroll_several | Scroll several screens down to Acknowledgments in this RFC page, and read its section heading aloud. | Exact RFC URL; changed AX scroll position; Acknowledgments in viewport OCR and reply; at least 3 scroll receipts. |
| public_long_list | Scroll through this Python release directory listing several times until 3.9.0 is visible; read that entry without opening it. | Exact Python release directory URL; 3.9.0 in viewport OCR and reply; at least 3 scroll receipts. |
| safari_new_tab | Use Command-T in this Safari window to create a fresh tab. | Owned Safari window gains exactly one tab. |
| safari_close_tab | Dismiss just the extra tab with Command-W, keeping the reference tab. | Tab counts restored to baseline and exact reference URL remains. |
| safari_private_open | Create a separate Safari window in Private Browsing mode and leave it open. | Exactly one new Safari window plus Private indicator in native AX. |

All fixture trees are created in setup and removed in finally, including setup/native-close failures. Saved TextEdit documents close without saving; fixture Info windows close explicitly. Notes and Reminders retain their existing per-title marker cleanup. The shared runner closes owned Safari/new windows and quits only newly launched safe apps; it never sweeps documents for this suite.

Owner requirements: drag cannot be confirmed by the existing eval route and is recorded as needs_owner. TextEdit typing/formatting can also wait for normal UI confirmation. Spaces is recorded as skipped (never a pass) when there is only one Space, multiple displays, or no reliable Space count. No permissions, model configuration, or confirmation allowlist is changed.

The checks fail closed when macOS labels/AX data differ or public pages change. Cursor evidence is sampled every 200 ms; very brief transitions can be missed. This suite measures the existing behavior; it does not change app behavior to make cases pass.
