# Latest recorded passing tasks

Evidence inspected on 2026-10-26. These are recorded passes, not a claim that every old check is strict. No live tasks were run for this change. Latest complete suite runs are used; later focused reruns do not replace an entire suite. Repeated wording within a run is listed once. Unsafe historical tasks are listed only as evidence and are excluded from harder.

## Default requests

Source: `.data/live_eval/requests-after/20261024-230816/summary.json`

- Microsoft Teams. — 1/1 passed
- read my second last email — 1/1 passed
- remind me to call mom at 6 — 1/1 passed
- open youtube and search for lo-fi — 1/1 passed
- open a new Safari window — 1/1 passed
- move to the left — 1/1 passed
- click the first email in Mail — 1/1 passed
- what's on my screen — 1/1 passed
- what do I have to do today — 1/1 passed
- open the calculator and add 12 and 30 — 1/1 passed
- are there any notifications that require my attention — 1/1 passed
- what number did I just say — 1/1 passed
- my name is Ana. what is my name? — 1/1 passed

## Navigation

Source: `.data/live_eval/20261024-133904/summary.json`

- open System Settings and go to Battery — 3/3 passed
- show me my Wi-Fi settings — 3/3 passed
- in System Settings, open Displays — 3/3 passed
- find the Bluetooth settings — 3/3 passed
- open Finder and go to the Downloads folder — 3/3 passed
- show me my Documents folder — 3/3 passed
- go to Wikipedia and open the article about Romania — 2/3 passed (partial reliability)
- open apple.com and go to the Mac page — 3/3 passed
- search DuckDuckGo for weather in Bucharest and open the first result — 2/3 passed (partial reliability)
- on Wikipedia, search for Bucharest and open the article — 3/3 passed
- open the Calendar in Teams — 1/3 passed (partial reliability)

## live_tasks / v2

Source: `.data/live_eval/20261025-220953/runs.jsonl`

- `finder_folder`: can you open Movies?
- `github_notifications`: show me my GitHub notifications
- `missing_app`: I want to use Notion
- `recipe`: look up how to make pesto and tell me what I need
- `dark_mode`: am I using dark mode or light mode?
- `safety_send`: email test@example.com that I am running late
- `go_back`: go back to the previous page
- `web_fact`: find out the speed of light in km per second
- `scroll_section`: take me to the History part of this article
- `switch_app`: bring Safari to the front
- `apple_section`: open apple.com and go to the iPhone page
- `two_tabs`: open apple.com and duckduckgo.com in two separate tabs
- `wiki_fact`: go to the Wikipedia article on Marie Curie and tell me what year they were born
- `app_search`: open Maps and find Lisbon
- `finder_search`: search my Mac for files named invoice
- `newest_file`: which file did I add last to Downloads?
- `safari_history`: where can I see the sites I visited? open it
- `notes_search`: search my notes for idea
- `translate`: how do you say "see you tomorrow" in Italian?
- `wiki_article`: look up Photosynthesis on Wikipedia
- `settings_pane`: where can I change Battery? open it
- `macos_version`: which macOS version is this Mac on?
- `textedit_type`: write 'Call the dentist about the cleaning' in a new TextEdit document
- `newest_pdf`: open the last PDF I downloaded
- `menu`: show me the View menu in Finder
- `battery`: how much battery do I have left?
- `weather_now`: what's the weather like in New York right now?
- `reminder_roundtrip`: set a reminder for on Friday at 5pm: A11y test 8758 water the plants

## live_hard / v3

Source: `.data/live_eval/20261025-222104/runs.jsonl`

- `rain_reminder`: if it is going to rain in Lisbon tomorrow, remind me "A11y test 7575: take an umbrella" tomorrow at 8, otherwise just tell me it will be dry
- `newest_download_size`: what's the size of the last thing I downloaded?
- `menu`: in Finder, open the Go menu
- `unread_mail`: how many unread emails do I have?
- `note_and_read_back`: make a note titled "A11y test 9725" that says the spare key is under the blue pot, then read it back to me
- `finder_sort`: open my Documents folder and sort it by date added
- `nth_story`: go to Hacker News and tell me the title of the fifth story
- `newest_pdf`: open the last PDF I downloaded
- `switch_tab`: go back to the Wikipedia tab I had open
- `warmer_city`: is it warmer in Madrid or Oslo right now?
- `reuse_open_site`: open GitHub
- `site_search`: search Apple's support site for battery
- `warmer_city`: is it warmer in Oslo or Hanoi right now?
- `apple_section`: open apple.com and go to the Support page
- `github_notifications`: check my GitHub notifications

## live_heldout

Source: `.data/live_eval/20261025-225855/runs.jsonl`

- `heldout_installed_memory`: In About this Mac, read how much memory is installed. Do not change any settings.
- `heldout_activity_memory`: Open Activity Monitor and show memory pressure, leaving all processes running.

## live_broad

Source: `.data/live_eval/broad-3/20261026-111830/summary.json`

- `finder_downloads`: Reveal my Downloads folder in a Finder window.
- `finder_folder_info`: Show me the info window for the Downloads folder.
- `preview_thumbnails`: Show the page thumbnails in Preview.
- `settings_wi-fi`: Show me my Wi-Fi settings.
- `settings_appearance`: Show me my Appearance settings.
- `settings_keyboard`: Show me my Keyboard settings.
- `settings_bluetooth`: Show me my Bluetooth settings.
- `textedit_multiline`: In the blank TextEdit document type these three lines exactly: A11y test 1793006310444495
Shopping for Saturday
Bread and apples
- `notes_create`: Create a note titled A11y test 17930063104444953 containing orchard picnic.
- `reminder_item`: Add a reminder titled A11y test 17930063104444955 check picnic basket, without a due date.
- `safari_public_page`: Go to rfc-editor.org/rfc/rfc2606 in Safari.

## live_conversation

Source: `.data/live_eval/conversation-4/20261026-121643/summary.json`

- `browser_followups`: open Safari and go to example.com
- `browser_followups`: now do the same with wikipedia.org
- `browser_followups`: do that again in Chrome
- `settings_followup`: open the Sound pane in System Settings
- `settings_followup`: now do it for Displays
- `two_notes`: make a note titled A11y test 1793009804094806 saying hi
- `two_reminders`: add a reminder A11y test 17930098040948061 for tomorrow at 9am
- `wikipedia_followup`: search Wikipedia for Bucharest
- `wikipedia_followup`: now for Cluj
- `thanks`: thanks, that was quick
- `why`: why did you open that?
- `correction`: you didn't do it


## Varied navigation (additional baseline)

Source: `.data/live_eval/20261024-154012/summary.json`

- look up Giraffe on Wikipedia — 1/3 passed (partial reliability)
- open Finder and go to Pictures — 2/3 passed (partial reliability)
- in this window, search for romeo and juliet — 3/3 passed
- I want to see my Bluetooth settings — 3/3 passed
- open calculator and compute 147 times 25 — 3/3 passed
- search the App Store for Notion — 3/3 passed
- close this Safari tab — 3/3 passed
- open Calendar and go to January 2027 — 3/3 passed
- open the Go menu in Finder — 3/3 passed
- use the calculator to work out 415 times 43 — 3/3 passed
- I want to see my Battery settings — 3/3 passed
- look up the word quixotic in the Dictionary app — 2/3 passed (partial reliability)
- look up Jazz on Wikipedia — 1/3 passed (partial reliability)
- show me Pictures in Finder — 2/3 passed (partial reliability)
- search for how tall is the eiffel tower here in this tab — 3/3 passed

## Newer incomplete broad run observed during implementation

Source: `.data/live_eval/broad-4/20261026-125053/runs.jsonl` (no summary.json at inspection; 21 turns recorded). The latest complete run above remains the baseline; these are the passes so far in the newer partial run.

- `finder_downloads`: Reveal my Downloads folder in a Finder window.
- `finder_folder_info`: Show me the info window for the Downloads folder.
- `preview_thumbnails`: Show the page thumbnails in Preview.
- `settings_wi-fi`: Show me my Wi-Fi settings.
- `settings_appearance`: Show me my Appearance settings.
- `settings_keyboard`: Show me my Keyboard settings.
- `settings_bluetooth`: Show me my Bluetooth settings.
- `textedit_multiline`: In the blank TextEdit document type these three lines exactly: A11y test 1793011853248429
Shopping for Saturday
Bread and apples
