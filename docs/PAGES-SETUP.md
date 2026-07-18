# decisionsynth.com — GitHub Pages setup (owner clicks)

The one-pager lives in this folder (`docs/index.html`, `docs/CNAME`). Per owner
decision 11.4 (2026-07-18): GitHub Pages on the org, DNS on Squarespace. To go
live (can precede the public launch — it's brand, not announcement; note the
repo must be public for Pages on the free plan, so in practice this lands with
the launch-day visibility flip):

1. **Enable Pages:** repo Settings → Pages → Source: "Deploy from a branch" →
   Branch `main`, folder `/docs` → Save.
2. **DNS (Squarespace):** point the apex at GitHub Pages —
   A records for `decisionsynth.com` → `185.199.108.153`, `185.199.109.153`,
   `185.199.110.153`, `185.199.111.153` (optionally `www` CNAME →
   `decisionsynth.github.io`).
3. Back in Settings → Pages: custom domain `decisionsynth.com` (the `CNAME`
   file here keeps it pinned), then check **Enforce HTTPS** once the
   certificate provisions.

Also in this repo, staged for launch-day repo polish (§8):
- `.github/social-preview.png` — upload at Settings → General → Social preview.
- `.github/org-profile-README.md` — copy into a new `decisionsynth/.github`
  repo at `profile/README.md` for the org landing at github.com/decisionsynth.
- Repo About panel: description, topics (`benchmark`, `agent-memory`,
  `synthetic-data`, `fintech`, `llm-evaluation`), website → decisionsynth.com.
