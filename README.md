# Eden Prairie News

News aggregation and light moderation-assist tool for r/edenprairie. Pulls
local news from RSS feeds, formats drafts for Reddit, and lets a mod review
and approve them from a local web UI before anything actually posts.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # optional first-run seed -- see Config page note below
```

`config/feeds.yaml` is only read once, to seed the feed list into the
database on first run. After that, manage Reddit credentials, the Discord
webhook, and RSS feeds from the **Config** link in the web UI's nav bar
instead of editing files -- changes there apply immediately, no restart.

## Running

```bash
.venv/bin/python -m edenprairie_news.pipeline    # one-off: fetch feeds, draft new posts, exit
.venv/bin/python -m edenprairie_news.web.app     # start the local review UI, reachable on the LAN at http://<this-machine's-LAN-IP>:1981
```

(`edenprairie-fetch` / `edenprairie-web` console scripts are also installed,
but depend on the editable install's `.pth` machinery working correctly in
your environment -- if they raise `ModuleNotFoundError: edenprairie_news`,
use the `python -m` form above, which doesn't depend on it.)

Both are on-demand — nothing runs in the background. Run the pipeline
whenever you want fresh news (cron/launchd if you want it automatic), then
review drafts and moderate current subreddit posts from the web UI, which
also has "Run pipeline now" and "Sync subreddit posts" buttons.

```bash
.venv/bin/pytest   # unit tests (parser/formatter, no network or DB)
```

## Subreddit moderation view

"Sync subreddit posts" pulls recent live r/edenprairie submissions into the
main page (separate from your own news drafts), each auto-tagged with
`action_flags` from `edenprairie_news/flag_rules.py` (e.g. missing flair,
has reports) and taggable by hand. Tag a post `hidden` (or click "Hide") to
drop it out of the default view without deleting anything -- click "Show
hidden posts" to bring it back.

## Security note

The web UI has no authentication and binds to `0.0.0.0:1981` (all
interfaces) by default, so it's reachable from anywhere on your LAN.
Anyone who can reach the port can approve posts (and, if Mod Queue is
enabled, take moderation actions) using the configured Reddit account's
credentials — only run this on a network you trust. Set
`WEB_HOST=127.0.0.1` in `.env` to restrict it to this machine only.

## Discord notifications

Set the Discord webhook URL (Config page, or `DISCORD_WEBHOOK_URL` in
`.env`) to get a message in a channel whenever the pipeline drafts new
articles. This is a plain webhook POST, not a bot — no token, nothing
persistent. See `CLAUDE.md` for the (deliberately deferred) plan for a
fully interactive bot.

## Reddit API policy

Use a **dedicated bot account** for `REDDIT_USERNAME`/the Config page's
Reddit fields — not your personal moderator account. Reddit's Responsible
Builder Policy prohibits mixed-use accounts (see `CLAUDE.md`'s "Reddit API
policy" section for the full review). That account doesn't need to be a
subreddit moderator just to post drafts; only check "Enable Mod Queue" on
the Config page if it is one.

From the Config page, prefer **"Connect via Reddit login"** over typing in
a username/password: it walks the account owner through Reddit's own OAuth
login page and saves a refresh token, so the account's raw password never
has to be stored by this app. Needs `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`
saved first, and the redirect URI shown on the Config page registered on
the app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps).

If you're setting up real Reddit credentials, also review Reddit's
[Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)
for anything specific it requires beyond what's already here (a
descriptive user agent, human approval before every post, PRAW's built-in
rate limiting).
