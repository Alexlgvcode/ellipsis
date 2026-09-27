# Hosting the live site

https://ellipsisnyc.tech stays on GitHub Pages. A small server runs the live backend at
`api.ellipsisnyc.tech`: the API, the live pipeline on the cameras (`scripts.live`) and the
worker (SUMO scoring, Gemini notes), behind Caddy for HTTPS. The site reads that API; if it
can't be reached within 4 s, the site plays the recording and says so. `?replay` and
`?sample` still open the recording and the sample incidents.

| What a visitor sees | When |
|---|---|
| **LIVE**, alerts from the cameras now | the server is up |
| LIVE, "No active incidents", with a *Watch a recorded incident* link | the server is up, nothing is happening (quiet streets, night) |
| **REPLAY**, with a line saying the live feed isn't reachable | the server is down or unreachable |

Only reads reach the API from outside: Caddy refuses every POST, so nobody can post fake
events or decisions. A visitor's Accept or Reject stays in their browser.

## Set up the server (once, about 30 minutes)

1. **Get a server.** DigitalOcean: *Create → Droplets*, Ubuntu 24.04, **Basic, Regular, 4 vCPU
   / 8 GB** ($48/month; the GitHub Student Pack gives $200 of credit), region **New York**, SSH
   key login. Hetzner's CPX31 (about €15/month) works the same way.
2. **Point the API's name at it.** At the registrar for ellipsisnyc.tech, add an **A record**:
   name `api`, value the server's IP address. Leave the records for the site as they are.
3. **Install and start it**, from your laptop:

   ```bash
   ssh root@<server-ip>
   curl -fsSL https://get.docker.com | sh
   ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
   git clone https://github.com/Alexlgvcode/ellipsis.git && cd ellipsis/deploy
   cp .env.example .env && nano .env          # GEMINI_API_KEY, ELEVENLABS_API_KEY
   docker compose up -d --build               # first build takes about 10 minutes
   ```

4. **Check it**: `curl https://api.ellipsisnyc.tech/health` should answer
   `{"status":"ok","mock_mode":false,"source":"live"}`. Caddy gets the certificate on the
   first request, once the DNS record has spread (a few minutes).
5. **Point the site at it.** On GitHub: *Settings → Secrets and variables → Actions →
   Variables → New repository variable*, `LIVE_API` = `https://api.ellipsisnyc.tech`. Then
   *Actions → Demo site → Run workflow*. Open https://ellipsisnyc.tech: the top bar says LIVE.

## Running it

| Task | Command (in `ellipsis/deploy` on the server) |
|---|---|
| Watch the pipeline and the worker | `docker compose logs -f live worker` |
| Deploy a new version of `main` | `git pull && docker compose up -d --build` |
| Restart everything | `docker compose restart` |
| Stop the live backend (the site falls back to the replay) | `docker compose stop` |
| CPU and memory | `docker stats` |

Everything restarts on its own after a crash or a reboot.

**Limits, set in `deploy/.env`:**
- `LW_NOTES_PER_DAY` (18): Gemini notes per day. The free tier allows 20 per model per day;
  after the cap, cards show without a note. If the worker log says `429 RESOURCE_EXHAUSTED`,
  that model's quota is used up for today (it resets at midnight Pacific): set another
  `LW_GEMINI_MODEL` (e.g. `gemini-3.8-flash` ↔ `gemini-3.7-flash`) and `docker compose up -d`.
- `LW_SIM_SEEDS` (`42`, in `compose.yml`): the worker scores each alert with one SUMO seed
  instead of three, so it keeps up on CPUs shared with YOLO. Gains are noisier with one seed.
- `LW_VOICE_PER_DAY` (40): new spoken alerts per day (ElevenLabs); ones already made keep playing.
- Frames are deleted after 30 minutes (`--keep-minutes` in `compose.yml`), so the disk
  doesn't fill up. Snapshots of alerts are kept.

**If detection can't keep up** (the `live` log says "detection is falling behind"): YOLO runs
on the CPU here, and 9–10 cameras every 2 s need 5 frames per second. Poll every 3 s
(`--interval 3` in `compose.yml`) or use the smaller model (`LW_YOLO_WEIGHTS=yolo11n.pt` in
`.env`), then `docker compose up -d`.
