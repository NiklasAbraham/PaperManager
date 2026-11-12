# marketing/

Public material about PaperManager: short films and the LinkedIn post. Everything here shows real library data
(paper titles, counts, figures) or the public chat demo; nothing private (notes, highlights, mail, keys).

| Folder | What |
|---|---|
| `reels/` | Vertical reels (1080x1920, H.264 + AAC, faststart, < 8 MB) with a poster `.webp` each. The blog serves copies from `niklasabraham.github.io/assets/papermanager/` under the same names. |
| `linkedin/` | `post.md` (the post text, the media in posting order with alt text) and the images it attaches. |
| `linkedin/old/` | The first post draft (agent setup angle) and its three images, kept for reference. |

## How the reels are made

The scripts live in ConceptsPlots, not here: `~/code/ConceptsPlots/100_code/110_reel_editor/` (see its README, section
"PaperManager UI reels"). In short: the frontend of the deployed commit runs against a small mock API that replays data
dumped read-only from the production library (`pm_ui/dump.py`, `pm_ui/mock_api.py`); Playwright records the UI
(`pm_ui/record.py`); the recording is cut with titles and a sound layer. Raw data and footage stay in
`ConceptsPlots/900_data/reel_edit/pm_ui/` (git-ignored).

To make a new one, follow that README; check every reel as a contact sheet and by listening (earshot) before it goes here.
