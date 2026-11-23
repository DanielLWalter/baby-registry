# Next steps

Handoff for the next session. See README.md for how everything works.

## State (2026-10-26)

- Live and refreshing hourly: https://daniellwalter.github.io/baby-registry/
- New "Everyday essentials" section above the pre-loved items, driven by `needs` in `docs/config.json`:
  Diaper fund, Formula fund (Bobbie Organic Whole Milk, $28 a can), and a postpartum doula night ($320).
  All three link to Venmo @danielwalter86; the section intro also offers a check to the shipping address.
- Wording the user asked to keep off the page: diaper brand names and a formula can count.

## Deploy retry (2026-11-23)

- Runs were failing several times a day at the Pages deploy step: "Found 0 artifact(s)" right after a
  successful upload (a GitHub-side timing glitch, worse since Nov 21). The workflow now waits 30s and
  retries the deploy once. If failures continue, check whether they're the retry failing too.

## Open ideas (not requested yet)

- All three funds go to one Venmo, so gifts can't be told apart unless guests write which fund in the note.
  Offered to add "put 'diapers' in the Venmo note" lines; user hasn't decided.
- "Everyday essentials" heading could be renamed now that the section is all funds.
