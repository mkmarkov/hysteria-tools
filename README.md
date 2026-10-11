# Hysteria Forever – Raid Roster

Live roster: **https://mkmarkov.github.io/hysteria-tools/**

A static page on GitHub Pages (`docs/`) that stores the roster in Firebase Firestore.
Anyone with the link can view and edit; changes appear on everyone's screen instantly.

## Files
- `docs/index.html` – the app (UI)
- `docs/ops.js` – roster rules (assign, move, leaders, specs…); every change runs in a Firestore transaction
- `docs/firebase-config.js` – Firebase web config (public by design)
- `docs/seed.json` – starting roster, used only if the Firestore document doesn't exist yet
- `firestore.rules` – security rules (paste into Firebase console → Firestore → Rules → Publish)

## Data & backups
- Roster: Firestore document `rosters/main` (`version`, `state`).
- The previous 50 versions: `rosters/main/backups/0..49` (slot = version % 50).
  To restore one, open the page, press F12 and run in the console:
  `rosterAdmin.importState(<state object from the backup>)`

## Local testing
```
python -m http.server 8790 --directory docs
```
Open http://localhost:8790 (uses the same live Firestore data).

## Old version
`server.py`, `start.bat`, `index.html` and `data/` are the earlier self-hosted version (Python + ngrok). No longer used.
