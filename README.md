# Baby registry

> **Moved (2026-10-23):** this project now lives in `~/Documents/Code/baby reg` (was `~/Desktop/baby reg`).

A registry page for secondhand finds on Poshmark and thredUP. Sold items drop off on their own.

**Live site:** https://daniellwalter.github.io/baby-registry/

## Adding items

Edit `links.txt` (works from the GitHub website or app: open the file → pencil icon → commit):

- **Poshmark:** paste the listing link on its own line. Short share links (`posh.mk/...`) work too; the
  checker swaps them for the full link. Anything that isn't a listing (a closet, a search) gets you an email.
- **thredUP:** nothing to do. Anything favorited on the shared wishlist shows up automatically.

The page refreshes within a couple of minutes of saving `links.txt`, and every hour on its own.

## Removing items

- Sold or unavailable items disappear automatically at the next check.
- To remove one by hand, delete its line from `links.txt`, or un-favorite it on thredUP.

## Everyday essentials (diapers, formula, doula…)

Things that don't sell out live in the `needs` list in `docs/config.json` and are always shown above
the pre-loved items. Each entry takes `title`, and optionally `detail`, `price` (free text, e.g.
`"$28 a can"`), `url` (makes the card a "Buy it here" link), and either `image` (a photo URL) or `icon`
(an emoji). They're never checked or removed automatically; delete an entry to take it off.

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

- **Check cron-job.org first.** It's what starts the update every hour (see "How it works").
  Log in at console.cron-job.org → Cronjobs → "Baby registry refresh" → History. A **401** or **403** there
  means the GitHub token was deleted or lost its permission: make a new one (below) and paste it into the
  job's `Authorization` header as `Bearer <token>`.

- **GitHub emails you when a run fails,** and a run fails whenever something needs fixing:
  - a line in `links.txt` that isn't a Poshmark listing or thredUP wishlist,
  - the thredUP wishlist growing past 120 items (only the first 120 get checked),
  - any item that hasn't been checked successfully for 6 hours. One failed check is usually a hiccup and
    gets no email; 6 hours of them means a link went bad, or Poshmark or thredUP changed their pages or
    started blocking the checker (if it's every item from one store, it's that).

  The page still updates with whatever could be checked. Open the failed run on GitHub: the reason is at
  the top, and lines starting with `WARN` in "Check every item" say what went wrong for each link. You'll
  get an email every hour until it's fixed.
- **Items that can't be checked for a day disappear from the page,** since they may have sold in the
  meantime. They come back as soon as a check succeeds.
- **GitHub switches workflows off after 60 days with no commits.** The bot commits an empty "Monthly check-in"
  if nothing else has been committed in 30 days, so this shouldn't happen. If it does: Actions →
  "Update registry" → "Enable workflow".

## How it works

`update.py` reads each link, records title, photo, price, size and availability in `docs/items.json`,
and `docs/index.html` displays everything that's still available. A GitHub Action
(`.github/workflows/update.yml`) runs it, commits `docs/items.json` when something
actually changed, adds the shipping address from the secret, and publishes `docs/` to GitHub Pages.

### What starts the updates

GitHub's own timer (`schedule:` in the workflow) is unreliable on free accounts: it often runs hours late
or skips runs entirely. So a free [cron-job.org](https://cron-job.org) job ("Baby registry refresh") starts
the workflow every hour through GitHub's API. GitHub's timer stays on as a backup.

- **The job:** `POST https://api.github.com/repos/DanielLWalter/baby-registry/actions/workflows/update.yml/dispatches`
  with body `{"ref":"main"}` and headers `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`,
  `X-GitHub-Api-Version: 2026-03-10`, `Content-Type: application/json`. Success is a 2xx response.
- **The token:** a GitHub fine-grained personal access token named "cron-job.org registry refresh"
  (Settings → Developer settings → Fine-grained tokens), with access to only this repo and only the
  **Actions: Read and write** permission. It can start this workflow and nothing else. It isn't stored anywhere
  but cron-job.org, so to replace it, make a new one with the same settings and paste it into the job.
- **API version:** GitHub has deprecated `2022-11-28` and stops accepting it on March 10, 2028. If the job starts
  failing with a version error, change the `X-GitHub-Api-Version` header to the newest version listed at
  docs.github.com/en/rest/about-the-rest-api/api-versions.

Things that are easy to break:

- **Failed checks never mark items sold.** If a site can't be reached, or returns incomplete data, items keep
  their last known status. An item is only marked gone when the store clearly says it's sold or removed.
  (The page does hide items that haven't been confirmed for a day; see "If updates stop".)
- **Poshmark** sometimes returns a normal-looking page carrying a 504 error instead of the listing.
  `update.py` retries those.
- **thredUP** product pages block automated requests, so all thredUP data comes from the shared-wishlist page.
  It also rejects requests with browser-style `Accept-Language` headers, so `fetch()` sends only a User-Agent.
  Sold thredUP items drop off the wishlist entirely rather than showing as sold.

To run a check locally: `python3 update.py` (standard library only; the local run won't include the address).
