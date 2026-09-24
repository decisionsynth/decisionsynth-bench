# decisionsynth.com — Vercel setup (owner clicks)

The one-pager lives in this folder (`docs/index.html`). **Owner decision
2026-07-18: host on Vercel** (supersedes decision 11.4's GitHub Pages choice).
Rationale: Vercel deploys from this repo while it is still **private**, so
decisionsynth.com can go live *before* the launch-day repo flip; it matches
how wealthschema.com and finantrix.com are already operated; and the page
gets Vercel Analytics. The former `docs/CNAME` file (GitHub Pages-specific)
has been removed.

## One-time setup (~5 minutes, all in web UIs)

1. **Create the project:** vercel.com → Add New… → Project → Import
   `decisionsynth/decisionsynth-bench`. (If the repo isn't listed, grant the
   Vercel GitHub App access to the `decisionsynth` org / this repo when
   prompted.)
2. **Configure before deploying:**
   - Framework Preset: **Other**
   - Root Directory: **`docs`**
   - Build Command: leave **empty** (it's a static page — Vercel serves the
     directory as-is)
   - Output Directory: leave default
3. **Deploy.** You'll get a `*.vercel.app` URL — sanity-check the page there.
4. **Domain:** Project → Settings → Domains → add `decisionsynth.com` (and
   optionally `www.decisionsynth.com`, redirecting www → apex). Vercel shows
   the records to set.
5. **DNS (Squarespace):** as instructed by Vercel — typically an **A record**
   for the apex `decisionsynth.com` → `76.76.21.21`, and if using www, a
   **CNAME** `www` → `cname.vercel-dns.com`. (Use the values Vercel displays;
   they are authoritative.) HTTPS certificates provision automatically.

After setup, every merge to `main` that touches `docs/` redeploys the page
automatically, and PRs get preview URLs.

## Still staged in this repo for launch-day polish (§8)

- `.github/social-preview.png` — upload at Settings → General → Social preview.
- `.github/org-profile-README.md` — copy into a new `decisionsynth/.github`
  repo at `profile/README.md` for the org landing at github.com/decisionsynth.
- Repo About panel: description, topics (`benchmark`, `agent-memory`,
  `synthetic-data`, `fintech`, `llm-evaluation`), website → decisionsynth.com.
