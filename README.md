# Eden Prairie News

[![Tests](https://github.com/identd113/redditEP/actions/workflows/tests.yml/badge.svg)](https://github.com/identd113/redditEP/actions/workflows/tests.yml)
[![License: GPL v3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)

A news aggregator and moderation helper for a local subreddit. It reads
local news from RSS feeds, drafts Reddit posts, and shows them to a human
moderator in a small web page. **Nothing is posted until a person presses
the button.** It was built for [r/edenprairie](https://www.reddit.com/r/edenprairie),
but the feeds, venue list and subreddit name are all settings, so it can be
pointed at another community.

## What it does

- **Drafts posts from RSS.** Each feed has its own parser, an optional
  relevance filter for broad metro feeds, and an age limit (default 30 days).
  A link is never added twice, even if a feed changes its tracking tags.
- **Human approval, no API key needed.** *Post to Reddit* opens Reddit's own
  pre-filled submit page and you press Post as yourself. The tool then
  matches your post back to the draft (by pasted link, or by reading the
  subreddit's public feed). An optional API route exists if you have
  credentials.
- **Events calendar.** Finds dates, times and places in articles and in an
  events RSS feed, lets you edit and approve them, and renders the approved
  ones as a wiki page for the subreddit.
- **Subreddit moderation view.** Syncs recent posts and flags ones that need
  attention (missing flair, reports). Flag rules are small functions in
  `edenprairie_news/flag_rules.py`.
- **Stats.** Read-only score, ratio and comment history for the posts you
  made.
- **Discord notice** (optional) when new drafts are ready, through a plain
  webhook.

Everything runs on demand. There is no scheduler or background service
unless you add one (cron or launchd).

## Quick start

Needs Python 3.11 or newer.

```bash
git clone https://github.com/identd113/redditEP.git
cd redditEP
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env        # optional; everything can be set on the Config page

.venv/bin/python -m edenprairie_news.pipeline   # fetch feeds and draft posts, then exit
.venv/bin/python -m edenprairie_news.web.app    # review page on http://localhost:1981
```

Use `python -m` as shown. The `edenprairie-fetch` and `edenprairie-web`
console scripts are installed too, but they can fail with
`ModuleNotFoundError` on some editable installs.

Open the **Config** page to add feeds, the subreddit name, and optional
Reddit and Discord settings. Changes apply on the next request, with no
restart. `config/feeds.yaml` only seeds the feed list on the first run;
after that the database is the source of truth.

To start the review page at login on macOS, copy
`scripts/launchd/com.example.edenprairie-news.plist` to
`~/Library/LaunchAgents`, replace the placeholder paths, and load it with
`launchctl`.

Run the tests with `.venv/bin/python -m pytest`. They need no network.

## Reddit credentials (optional)

Drafting, the browser posting route, events and the wiki text work without
any Reddit login. Credentials are only for the API posting route, the mod
queue, subreddit sync and the stats refresh.

- **Stats and sync** need only an app client id and secret (create a
  "script" app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps)).
- **API posting and wiki updates** also need an account. Use the Config
  page's **Connect via Reddit login**. It stores a refresh token, so the
  password is never saved.
- Use a **dedicated account** for the tool, not your personal one. Reddit's
  [Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)
  forbids mixed-use accounts. That account does not need to be a moderator
  unless you turn on the mod queue.
- Set a descriptive `REDDIT_USER_AGENT` that names you as the contact.

## Security: read this before running it

The web page **has no login**. By default it listens on every network
interface (`0.0.0.0:1981`), so anyone who can reach the port can approve
posts and, with credentials set, act as the configured Reddit account. Run
it only on a network you trust, or set `WEB_HOST=127.0.0.1` in `.env` to
keep it on your own machine. Never put it on the public internet. Flask
debug mode is off unless you set `WEB_DEBUG=1`, which also exposes a code
console, so leave it off.

## Status and known gaps

This is a working personal project, not a finished product.

- The public-feed matching, Reddit's pre-filled `text` body, the stats
  refresh and the wiki update are tested against samples and fakes, **not
  yet against live Reddit**. Reddit often rate limits or blocks anonymous
  feed reads, in which case the page says so and you paste the post link by
  hand.
- Some sites refuse scripted feed requests. Find the feed address in a
  normal browser and add it on the Config page.
- Event extraction reads only the title and feed summary, not the full
  article, and a deadline such as "registration opens Dec. 1" can look like
  an event. A reviewer rejects those.
- Whether a moderator tool built this way needs Reddit's developer or app
  review is unresolved. Check Reddit's current policies before using it on
  a subreddit you moderate.

## Contributing

Issues and pull requests are welcome. Please run the tests first. The code
is organised as a pipeline of small modules (`reader`, `feed_parsers`,
`formatter`, `storage`) wired together in `pipeline.py`; new feed types
plug in as a parser module rather than reaching into other stages.
`CLAUDE.md` has a longer architecture tour.

## License

GNU General Public License, version 3. See [LICENSE](LICENSE). You may use
and modify this code, but a modified version that you share must also be
released as source under the GPLv3.
