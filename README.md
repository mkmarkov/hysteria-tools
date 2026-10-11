# Hysteria Forever – Raid Roster

## Start
```
python server.py
```
Open http://localhost:8787

Anyone with the link can view and edit (no password). Every change is backed up in `data/backups/`.

## Share with ngrok
Quickest: double-click `start.bat` (starts the server + ngrok; the public link is on the "Forwarding" line).

Manual steps:
1. Sign up at https://ngrok.com and install ngrok.
2. `ngrok config add-authtoken <your token>` (one time)
3. `ngrok http 8787`
4. Send people the `https://….ngrok-free.dev` URL.

Notes: your PC and `server.py` must stay running. The free URL changes each time you restart ngrok unless
you use your free static domain: `ngrok http --url=<your-domain>.ngrok-free.app 8787`.
Visitors see a one-time ngrok warning page – click "Visit Site".
Free ngrok allows ~20,000 requests/month. Open pages long-poll (about 2–3 requests/minute) and stop
completely when the tab is hidden or idle for 15 minutes, so normal use stays well inside that.

## Data
- `data/roster.json` – everything (players, groups). Edit by hand only while the server is stopped.
- `data/backups/` – the last 50 versions, one per change. Copy one over `roster.json` to roll back.
