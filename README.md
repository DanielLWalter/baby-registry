# Baby registry

A registry page for secondhand finds on Poshmark and thredUP. Sold items drop off on their own.

**Live site:** https://daniellwalter.github.io/baby-registry/

## Adding items

Edit `links.txt` (works from the GitHub website or app: open the file → pencil icon → commit):

- **Poshmark:** paste the listing link on its own line.
- **thredUP:** nothing to do. Anything favorited on the shared wishlist shows up automatically.

The page refreshes within a couple of minutes of saving `links.txt`, and every 30 minutes on its own
(GitHub sometimes starts scheduled runs a few minutes late).

## Removing items

- Sold or unavailable items disappear automatically at the next check.
- To remove one by hand, delete its line from `links.txt`, or un-favorite it on thredUP.

## Changing the title or welcome note

Edit `docs/config.json`.

## Changing the shipping address

The address isn't stored in this repo. It's the `SHIP_TO` secret under
Settings → Secrets and variables → Actions. To change it, edit that secret, then re-run the workflow
(Actions → "Update registry" → Run workflow).

## Privacy

- **Never put the shipping address in any file in this repo.** The repo is public. Use the `SHIP_TO` secret.
- The address is published scrambled and only shown when a guest taps "Show shipping address",
  so crawlers, scrapers and link previews don't see it in plain text. Anyone with the link can still reveal it.
- The page asks search engines not to index it (`<meta name="robots" content="noindex, …">`).

## If updates stop

- **GitHub emails you when a run fails.** Check Actions → "Update registry" → the failed run → "Check every item".
  Lines starting with `WARN` show which links couldn't be read. Those items keep their last known status.
- **GitHub pauses scheduled runs after 60 days with no commits.** The bot only commits when an item
  changes, so a quiet stretch can trigger this. To restart: Actions → "Update registry" → "Enable workflow".
- **If every item fails,** Poshmark or thredUP has probably changed their page layout or started blocking
  the checker, and `update.py` needs updating.

## How it works

`update.py` reads each link, records title, photo, price, size and availability in `docs/items.json`,
and `docs/index.html` displays everything that's still available. A GitHub Action
(`.github/workflows/update.yml`) runs it every 30 minutes, commits `docs/items.json` when something
actually changed, adds the shipping address from the secret, and publishes `docs/` to GitHub Pages.

Things that are easy to break:

- **Failed checks never remove items.** If a site can't be reached, or returns incomplete data, items keep
  their last known status. An item is only marked gone when the store clearly says it's sold or removed.
- **Poshmark** sometimes returns a normal-looking page carrying a 504 error instead of the listing.
  `update.py` retries those.
- **thredUP** product pages block automated requests, so all thredUP data comes from the shared-wishlist page.
  It also rejects requests with browser-style `Accept-Language` headers, so `fetch()` sends only a User-Agent.
  Sold thredUP items drop off the wishlist entirely rather than showing as sold.

To run a check locally: `python3 update.py` (standard library only; the local run won't include the address).
