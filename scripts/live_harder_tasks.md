# Harder live task manifest

Run manually with `.venv/bin/python scripts/live_eval.py --suite harder --runs 1`. This is opt-in, like broad and conversation; `all` is unchanged. Thirty turns in twenty-one cases. Markers below are examples: each build uses fresh digits. Follow-up turns share the same conversation and app state. Every turn also rejects failure replies.

Baseline evidence: [latest recorded passes](live_harder_baseline.md).

| Name | Request | Real end-state check | Passed task extended |
|---|---|---|---|
| settings_input_first | Take me to the place in System Settings for changing how the keyboard behaves. | Keyboard pane via settings_pane_is | broad settings_keyboard/bluetooth/wi-fi; conversation settings_followup |
| settings_input_follow | And now the pane for sound, without changing any values. | Sound pane via settings_pane_is | broad settings_keyboard/bluetooth/wi-fi; conversation settings_followup |
| settings_wireless_first | I need to see where wireless accessories are managed in System Settings; just show the pane. | Bluetooth pane via settings_pane_is | broad settings_keyboard/bluetooth/wi-fi; conversation settings_followup |
| settings_wireless_follow | Now show the Wi-Fi pane there, leaving the connection alone. | Wi-Fi pane via settings_pane_is | broad settings_keyboard/bluetooth/wi-fi; conversation settings_followup |
| settings_reading | In System Settings, take me down to Accessibility so I can look at the reading options. Leave everything as it is. | Accessibility pane via settings_pane_is | broad settings_appearance; navigation Battery/Bluetooth |
| settings_look | Show me where the light and dark appearance choices live in System Settings, without switching either one. | Appearance pane via settings_pane_is | broad settings_appearance; navigation Battery/Bluetooth |
| finder_nested | In this Finder folder, go into Recipes and then Saturday. | Exact Finder target is fixture Recipes/Saturday | v3 Documents sort/date added; broad finder_downloads; v2 TextEdit typing |
| finder_sort | Put this Finder folder into list view and arrange its items by name. | Exact fixture folder, list view, Name sort column | v3 Documents sort/date added; broad finder_downloads; v2 TextEdit typing |
| finder_info | Show the information window for this orchard folder in Finder, so I can see its details. | Exact fixture folder Info window exists | broad finder_folder_info |
| finder_read | Open the file called A11y test <digits> packing.txt from this Finder folder and tell me what it says to pack. | Exact opened TextEdit path, unchanged fixture file contents, reply contains amber lantern | v3 Documents sort/date added; broad finder_downloads; v2 TextEdit typing |
| web_rfc | In Safari, take me to rfc-editor.org/rfc/rfc2606 and tell me the RFC number shown there. | RFC URL on rfc-editor.org and reply contains 2606 | broad safari_public_page; conversation browser_followups |
| web_reference_follow | Now use that same Safari window to visit iana.org/domains/reserved. | Exact IANA reserved-domains URL | broad safari_public_page; conversation browser_followups |
| web_apple_support | Start at apple.com in Safari, then take me to its Support page. | support.apple.com URL | v3 Apple Support; v2 Apple iPhone; conversation browser_followups |
| web_apple_follow | In that window, go to apple.com and find the iPad page instead. | Exact apple.com/ipad URL | v3 Apple Support; v2 Apple iPhone; conversation browser_followups |
| web_screen_answer | Visit example.org in Safari and read me the heading on that page. | example.org URL, Example Domain tab title, reply contains Example Domain | broad safari_title (broad-2); requests screen inspection |
| web_lower_section | Open python.org in Safari, then follow the link to the downloads page. | Exact python.org/downloads URL | v2 Apple iPhone; v3 Apple Support |
| preview_sidebar | In Preview, bring back the little page pictures on the left of this two-page document. | Exact test PDF window title and checked Thumbnails menu item | broad preview_thumbnails |
| preview_name | Keep those thumbnails showing and tell me the filename of this PDF. | Same PDF and thumbnails state, reply contains exact filename | broad preview_thumbnails |
| textedit_lines | Type the following exactly into this empty TextEdit file, keeping the line breaks: / A11y test <digits> / Saturday picnic / Bring pears and a blanket. | Exact opened fixture file path and complete three-line document text | v2 TextEdit sentence; broad textedit_multiline (proposal check replaced) |
| textedit_sentence | Type the following exactly into this empty TextEdit file, keeping the line breaks: / A11y test <digits> / The spare umbrella is beside the boots. | Exact opened fixture path and complete two-line document text | v2 TextEdit sentence; broad textedit_multiline (proposal check replaced) |
| note_picnic | Please make a note called A11y test <digits> with exactly this body: Bring the green blanket and two pears. | Exactly one note with exact title and complete body | broad notes_create/reminder_item; conversation two_notes/two_reminders first turns |
| note_follow | Make another note like that, titled A11y test <digits>, but with exactly this body: Leave the basket by the door. | Exactly one second note with exact title and complete body | broad notes_create/reminder_item; conversation two_notes/two_reminders first turns |
| reminder_morning | Put A11y test <digits> in Reminders for tomorrow at 8 in the morning. | Exactly one reminder with exact title and tomorrow 08:00 due date | broad notes_create/reminder_item; conversation two_notes/two_reminders first turns |
| reminder_follow | Add another for tomorrow at 2 in the afternoon, this time called A11y test <digits>. | Exactly one second reminder with exact title and tomorrow 14:00 due date | broad notes_create/reminder_item; conversation two_notes/two_reminders first turns |
| lookup_memory | Go to About in System Settings and read out the installed memory in GB, without changing anything. | About pane plus reply GB value matches sysctl hw.memsize | heldout About memory |
| lookup_dictionary | Look up nocturnal in Dictionary and tell me what it means. | Dictionary foreground, native text contains nocturnal/night, reply contains night | varied Dictionary quixotic (2/3; partial baseline) |
| mascot_corners_0 | Please tuck yourself into the upper-left corner of my screen. | Actual mascot geometry within 40 px of requested screen corner | requests move to the left |
| mascot_corners_1 | Now move yourself over to the lower-right corner of my screen. | Actual mascot geometry within 40 px of requested screen corner | requests move to the left |
| mascot_edges_0 | Please tuck yourself into the upper-right corner of my screen. | Actual mascot geometry within 40 px of requested screen corner | requests move to the left |
| mascot_edges_1 | Now move yourself over to the lower-left corner of my screen. | Actual mascot geometry within 40 px of requested screen corner | requests move to the left |

## Limits and cleanup

- Latest broad textedit_multiline accepted a proposal as evidence. Harder replaces this with an actual document-content check; confirmation may therefore leave a task failing until an owner confirms through the normal UI. The eval socket only confirms its existing restricted app_write proposals.
- Dictionary quixotic passed only 2/3 in the latest varied run; its harder variant is deliberately marked as extending a partially reliable baseline. AX/menu availability and English labels can make native checks fail closed.
- The latest broad safari_title failed; the heading-answer variant extends the earlier broad-2 pass and the default screen inspection pass. The older default Calculator check was reply-only, so no new Calculator result check relies on it.
- All writes carry A11y test plus digits. Notes/reminders use separate per-title clean_items callbacks in the runner finally block. TextEdit uses pre-created temporary saved documents and checks their in-memory full contents. It never moves iCloud files to Trash. Temporary fixture trees are removed even when their close operation fails.
- The shared runner closes newly opened windows, closes the owned Safari window, reuses running apps, and quits only newly launched safe apps. No test quits an already running app. Finder Info has explicit exact-title cleanup. Mascot cleanup parks it at bottom right using the local geometry route; it does not restore arbitrary original pixel coordinates.
- No live evaluation was run. External sites may redirect or change, and native menu/path representations still need verification on this Mac. Redirect checks accept only the explicitly listed RFC alternatives. Tomorrow is evaluated in local time; avoid crossing midnight during reminder cases.
- Historical passes involving private/communication apps and the blocked video site are evidence only; they are not in this suite. Other passed families were sampled into the requested thirty-turn scope, not exhaustively expanded.
