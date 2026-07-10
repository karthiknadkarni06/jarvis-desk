# Jarvis Cloud Desk — autonomous paper trading (NIFTY option buying)

Runs itself on GitHub Actions every ~20 min during Indian market hours.
No computer needed on your side. Paper trading only — never places real orders.

## One-time setup (~10 min, from any device)

1. **Create the repo**: github.com → New repository → name `jarvis-desk` → **Public** → Create.
2. **Upload these files** (Add file → Upload files): drag in everything from this folder
   *including the `.github` folder* (keep the folder structure).
3. **Add secrets**: repo → Settings → Secrets and variables → Actions → New repository secret:
   - `DHAN_TOKEN` = your Dhan Data API access token (from DhanHQ portal → Generate Access Token)
   - `DHAN_CLIENT_ID` = your Dhan client ID
4. **Enable Pages**: Settings → Pages → Source: Deploy from a branch → Branch: `main`, folder `/ (root)` → Save.
   Your dashboard URL will be: `https://<username>.github.io/jarvis-desk/`
5. **Test now**: repo → Actions tab → "Jarvis Paper Desk" → Run workflow. Green check = working.

That's it. The engine now runs automatically every trading day, 9:10–15:30 IST.
Open the dashboard URL anytime from phone or office — it always shows the live ledger.

## Notes
- Token expires periodically (Dhan tokens usually last months on the Data plan) — if runs start
  failing with auth errors, regenerate the token in DhanHQ and update the secret.
- GitHub cron can drift a few minutes — normal, harmless.
- To pause the desk: Actions tab → Jarvis Paper Desk → "..." → Disable workflow.
- NEVER put the token in any file — only in Secrets. (Repo is public.)
