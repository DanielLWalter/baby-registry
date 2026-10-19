# Baby registry

A public registry page for secondhand finds on Poshmark and thredUP. Sold items drop off on their own.

## Adding items

Edit `links.txt` (works from the GitHub website or app: open the file → pencil icon → commit):

- **Poshmark:** paste the listing link on its own line.
- **thredUP:** nothing to do. Anything favorited on the shared wishlist shows up automatically.

The page refreshes within a couple of minutes of saving `links.txt`, and every 30 minutes on its own.

## Removing items

- Sold or unavailable items disappear automatically at the next check.
- To remove one by hand, delete its line from `links.txt`, or un-favorite it on thredUP.

## Changing the title or welcome note

Edit `docs/config.json`.

## Changing the shipping address

The address isn't stored in this repo. It's the `SHIP_TO` secret under
Settings → Secrets and variables → Actions, and it's added to the page (scrambled, revealed by a button) when it's published.
After changing it, re-run the workflow (Actions → "Update registry" → Run workflow).

## How it works

`update.py` reads each link, records title, photo, price, size and availability in `docs/items.json`,
and `docs/index.html` displays everything that's still available. A GitHub Action
(`.github/workflows/update.yml`) runs it on a schedule and publishes `docs/` to GitHub Pages.
If a site can't be reached during a check, items keep their last known status instead of disappearing.

To refresh by hand: GitHub → Actions → "Update registry" → Run workflow.
