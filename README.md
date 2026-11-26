# RetroTV — a 90s-style scheduled TV guide

Repo layout: the app lives at the root (`server.py`, `static/`, `media/`);
the product agent that keeps this repo shipping lives in [`agent/`](agent/README.md).

Parents pre-program what plays, kids tune into a channel and watch whatever is on.
No browsing, no on-demand — just like TV in the 90s. Includes labeled mid-show
"commercial breaks" (e.g. **Bathroom Break**) that interrupt playback for a set time.

## Run it

```bash
cd retrotv
python3 server.py
```

- Kids TV: `http://127.0.0.1:8000/` (big power button, then channel buttons only)
- Parent console: `http://127.0.0.1:8000/parent` (default PIN `1234`)

From a phone on the same Wi-Fi, run with `RETROTV_HOST=0.0.0.0 python3 server.py`
and open `http://<your-computer's-ip>:8000/` on the phone.

Zero dependencies — Python 3 stdlib only. Data lives in `data/db.json`.

## How it works

- **Library** — your shows/movies: title, type, length, optional video file.
  Drop `.mp4`/`.webm`/`.mkv` files into `media/` and pick them in the parent view.
  Items without a file render a calm test-pattern stand-in.
- **Schedule** — each entry = a library item on a channel with a start time.
  Blocks play in time order; gaps show OFF AIR (static). Move/delete blocks freely.
- **Breaks** — attach to any scheduled block: label + start minute + duration.
  While a break is "on air", every tuned-in kid sees the break screen with a
  countdown, then the show resumes exactly where it paused.
- **Channels** — three, numbered like the 90s (CH 3 / 4 / 5), renameable.
- **Now-playing engine** — the server computes, per channel, `program` / `break` /
  `offair` plus the exact playback offset; the kids view polls `/api/now` and syncs
  the video to it (joining mid-show, just like real TV).

## Project breakdown

| Phase | Piece | Status |
|---|---|---|
| 1 | Server (stdlib HTTP, JSON store, now-playing engine, PIN auth) | done |
| 1 | Kids view `/` — retro CRT TV (VHF/UHF channel knobs, power switch, OSD blip), synced playback, break + off-air screens | done |
| 1 | Parent view `/parent` — schedule, library, breaks, channels, PIN | done |
| 1 | Real video files via `media/` with HTTP Range support | done |
| 2 | TV-Guide-style grid (what's on tonight/week) in parent view | todo |
| 2 | Recurring daily blocks ("cartoons every Sat 9am") | todo |
| 2 | "Remote control" phone page (channel up/down, volume) | todo |
| 3 | Multiple profiles / per-kid PINs, viewing-time limits | todo |
| 3 | Chromecast/AirPlay-style casting of the kids screen | todo |

## API sketch

- `GET /api/now` — per-channel now-playing state (no PIN; kids view)
- `POST /api/parent/login|data` — PIN check / full data dump
- `POST /api/parent/library/add|delete`
- `POST /api/parent/schedule/add|delete|setstart`
- `POST /api/parent/break/add|delete`
- `POST /api/parent/channel/rename`, `POST /api/parent/pin/change`

All parent endpoints take `{"pin": "...."}` in the JSON body.

## Notes

- The PIN is a kids-vs-parents convenience, not real security — traffic is plain
  HTTP on your home LAN. Don't expose the port publicly.
- Everything is local: no accounts, no cloud, no tracking.
