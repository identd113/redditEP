# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

News aggregation + moderation-assist tool for r/edenprairie, built for a
subreddit moderator. Pulls local news from RSS, formats it as Reddit posts,
and requires human approval before anything is actually posted. Everything
runs on-demand (no daemon/scheduler) and the web UI is meant for LAN-only,
trusted use — it has no authentication of its own.

## Commands

```bash
# setup (once)
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env        # fill in Reddit credentials + optional Discord webhook

# run (python -m, not the console scripts -- see note below)
.venv/bin/python -m edenprairie_news.pipeline     # one-off: fetch feeds -> draft new posts -> exit
.venv/bin/python -m edenprairie_news.web.app      # start review UI (binds 0.0.0.0:1981 by default, LAN-reachable)

# test
.venv/bin/pytest                     # all tests
.venv/bin/pytest tests/test_formatter.py::test_format_title_includes_source_and_truncates  # single test
```

There is no separate lint/build step configured yet.

`edenprairie-fetch`/`edenprairie-web` console scripts are also declared in
`pyproject.toml`, but this dev environment's editable install has a flaky
`.pth`-processing quirk (the generated `.pth` file's `install()` call
doesn't always register at interpreter startup) that intermittently breaks
them with `ModuleNotFoundError: edenprairie_news`. `python -m` doesn't
depend on that mechanism at all, so prefer it when developing/debugging.

## Architecture

### Pipeline: reader -> feed_parsers -> formatter -> storage

Each stage is a standalone module with no knowledge of the others, wired
together only in `edenprairie_news/pipeline.py::run_pipeline()`. This is the
seam to preserve when adding features — new stages should plug into
`run_pipeline()` rather than reaching into each other directly.
`run_pipeline()` loops over `storage.list_feeds()` sources one at a time
(not flattened together), so each source's parser strategy and
relevance-filter tag apply only to its own entries.

- `reader.py` — talks to `feedparser`, returns raw, uncleaned `RawEntry`
  objects for one `FeedSource` (url, source, title, summary_html,
  published_at, author, image_url). No filtering, no dedup, no HTML
  cleaning. `_extract_image()` tries `media_thumbnail` →
  `media_content` → an image enclosure link → a fallback `<img>` parsed out
  of the entry's own summary HTML, returning `None` if a feed just doesn't
  have one (e.g. the seeded Google News feed is text-only — no images from
  that source is expected, not a bug).
- `feed_parsers/` — per-feed parsing strategy registry. `FeedSource.parser`
  (set per-feed on the Config page, default `"default"`) selects a
  `parse_entry(RawEntry) -> Article` function via `feed_parsers.get_parser()`.
  `default.py` just strips HTML from the feed's own summary and passes
  author/image_url through. Add a new source-specific strategy (e.g. one
  that fetches the full article page because a feed only gives truncated
  summaries) as a new sibling module + one line in
  `feed_parsers/__init__.py`'s `PARSERS` dict — no other file needs to
  change.
- `parser.py` — shared parsing utilities used by strategies in
  `feed_parsers/`: `clean_html()` and `filter_relevant()` (an optional
  keyword filter applied only when a feed is tagged `needs-filter`, for
  broad/metro feeds that aren't already Eden-Prairie-scoped — set via the
  Config page's "relevance filter" checkbox, stored on `FeedSource.tags`).
- `formatter.py` — pure string transforms, `Article -> (title, body)`. No
  I/O, so formatting-rule changes are trivial to unit test. Body includes a
  `"By {author}"` byline line when the source provided one.
- `storage.py` — raw-SQL SQLite persistence (no ORM), four independent
  tables: `articles` (news drafts, state machine below), `subreddit_posts`
  (live subreddit moderation view, see below), `settings` and `feeds`
  (DB-backed runtime config, see below). `insert_new_articles()` is where
  dedup against previously-seen URLs happens. Adding a column to an
  existing table needs an entry in `ARTICLES_MIGRATIONS` (or the equivalent
  pattern for other tables) since `CREATE TABLE IF NOT EXISTS` doesn't
  retroactively add columns — see `_migrate_articles_columns()`.
- `reddit_client.py` — PRAW wrapper. Auth is a "script" app using the mod
  account's username/password (password grant), which is issued a token
  scoped to everything that account can already do on the subreddit —
  posting, modqueue, approve/remove — with no separate scope list to
  request. Also has `already_posted_on_reddit()`, which checks Reddit
  itself (not just the local DB) for an existing submission of a URL before
  posting — an idea borrowed from Epicfisher/reddit-rss-bot, to catch posts
  made outside this tool.
- `notifier.py` — fire-and-forget Discord webhook POST when new drafts are
  ready. No bot, no token, no persistent connection; silently no-ops if
  `DISCORD_WEBHOOK_URL` is unset.
- `web/app.py` — Flask routes over the same `storage.py`/`reddit_client.py`
  functions the CLI pipeline uses. This is the human approval point: drafts
  sit in the `drafted` status until a mod approves or rejects them here.

### Article status state machine (in `storage.py`)

```
new -> drafted -> sent -> posted
              \        \-> drafted (reopened: "Not posted, back to drafts")
   any of them -> removed -> drafted / posted (Restore)
```

- `new`: inserted by the pipeline, not yet formatted.
- `drafted`: has `post_title`/`post_body` set, waiting for a mod in the web
  UI.
- `sent`: the mod pressed **Post to Reddit** (`POST /articles/<id>/send`). That records the article
  as sent *and* redirects (303) to Reddit's own pre-filled submit page (`reddit_link.submit_url()`),
  where the mod presses Post as themselves. No API key is involved. A sent article is out of the
  drafts, so it cannot be sent twice, and it waits for its Reddit post to be linked.
- `removed`: taken off every list by the **Remove** button (the only way to dismiss an article; the old separate
  "rejected" status was merged into it, existing rows were migrated). The link stays blocked from being re-added.
- `posted`: linked to its Reddit post (`reddit_url`, `reddit_post_id` set), either by the API route
  ("Post with the API", only shown when Reddit credentials are configured), by `matching.match_posts()`,
  or by pasting the post's address (`POST /articles/<id>/link`).
- `rejected`: mod declined it, or `already_posted_on_reddit()` caught a
  duplicate at approval time.

### Posting without an API key: send, then match

Reddit no longer hands out API keys freely, and a tool that posts through an API as a moderator raises
the policy questions below. So the default path is the human one: **Post to Reddit** opens Reddit's
pre-filled submit page and the mod posts it. The three modules that make this work, all independent of
`reddit_client.py` (PRAW stays for the optional API route and the mod queue):

- `reddit_link.py` -- pure: `submit_url()` (subreddit, title, body -> pre-filled link), `post_id_from_url()`,
  `normalize_url()` (host case, `www.`, trailing slash, tracking parameters, fragment) so the same story matches
  however its link was written.
- `reddit_public.py` -- read-only fetch of the subreddit's public Atom feed (`/r/<sub>/new.rss`), no key.
  It is rate limited and often refused (checked 2026-11-19: JSON 403, RSS 429 from this host), so it never
  retries and raises `RedditUnavailable` with a plain reason that the page shows. **Not yet confirmed against
  a live answer**; `parse_feed()` is tested against a hand-written Atom sample, not Reddit's real output.
- `matching.py` -- `match_posts()` links `drafted`/`sent` articles to posts whose link or text contains the
  article URL, and marks them `posted` with the permalink. The index page's "Check Reddit for my posts" runs it
  over the public feed plus the synced `subreddit_posts`.

Pasting a post's address under "Sent to Reddit" always works when the feed is unavailable.
**Not yet verified:** that Reddit's submit page keeps a long pre-filled `text` body (title and link are
reliable). Click Post to Reddit once on a real draft before relying on it.

### The front page: tabs on the left

`/?tab=<drafts|sent|posted|subreddit|removed>` (default `drafts`; the `subreddit` tab is labelled `r/<subreddit>`).
Vertical tabs with counts down the left, a strip across the top on a phone. Each tab holds its own buttons:
Drafts has "Run pipeline now", the obituary toggle and a **source filter** (`?source=<feed name>`: one chip per feed
with a count, Eden Prairie's own feeds first, nearby-city feeds after them with a dashed outline); Eden Prairie
drafts always list before nearby ones. Sent has "Check Reddit for my posts", Posted has "Refresh stats", the
subreddit tab has "Sync subreddit posts" and the hidden-posts toggle, Removed lists everything with Restore.
Actions redirect back to their own tab (e.g. a sync lands on the subreddit tab); Remove and Restore return to the
page you were on.

### Running it, and what the feeds give (checked 2026-11-19)

The review UI runs as the LaunchAgent `com.example.edenprairie-news` (`scripts/launchd/*.plist`, installed
in `~/Library/LaunchAgents`, log `~/Library/Logs/edenprairie-news.log`): port 1981, LAN only, no login.
Flask debug mode is **off** unless `WEB_DEBUG=1` (debug serves a code console to anyone on the network).
Links sent to other devices use the Mac's LAN address (`WEB_BASE_URL` overrides, `config.WebConfig.base_url`).
Pages carry a viewport tag and a phone stylesheet. Pipeline: `python -m edenprairie_news.pipeline`;
`pipeline.backfill_events()` re-runs event extraction on stored articles.

**The seeded Google News feed only gives headlines** (its "summary" is the headline again, 38-129
characters), so it yields drafts but **no events** (first run: 23 articles, 0 events, correctly). It also
brings in noise (property listings, obituaries) -- consider the relevance filter or other feeds.
Event extraction needs feeds whose summary carries the details. Checked from this host: the city site
(edenprairie.org) answers 403 "Access Denied" to scripts, `hometownsource.com` Sun Sailor 429; neither
feed address was confirmed. Find feed addresses in a normal browser and add them on the Config page.

### Age limit

Articles published more than `max_article_age_days` ago are not drafted (`parser.filter_recent()`, applied in
`pipeline._process_source`): default **30**, set on the Config page ("How old an article may be") or with
`MAX_ARTICLE_AGE_DAYS`; 0 turns it off; articles with no readable date are kept. The Config page also has a
one-off button that removes the stored drafts already older than the limit (status `removed`, so Restore works
and the links stay blocked); posted, sent and rejected articles are never touched. Never run automatically.

### Removing articles, and never adding a link twice

(Remove is a solid red button, `button.danger`, so it stands out.)

Every article tile has **Remove** (`POST /articles/<id>/remove`): status `removed`, off every list, listed under
"Removed" with **Restore** (back to Posted if it had a Reddit post, otherwise to the drafts). The row is kept on
purpose: `insert_new_articles()` skips any link whose normalised form (`articles.url_key`, via
`reddit_link.normalize_url`: tracking parameters, `www.`, case, fragment, trailing slash removed) matches an
existing row of **any** status, so a removed, rejected or posted link is never added again, even when a feed
changes its tracking tag. Removing a posted tile only hides it; the Reddit post is untouched, and it is no longer
tracked by Stats.

### Editing and removing events

Every event tile on `/events` has **Remove** (stored as status `rejected`; the old "Not an event" button is gone). A
removed event is never suggested again by `event_feeds.import_events` (`storage.event_already_known`) and is listed
under "Removed events" with **Restore**. Events already on the calendar (approved) are editable: "Edit this event"
opens the same fields (what, dates, times, where, website) and shows the exact wiki line. Edits and hand-added events
share one check, `app._event_problem` (valid dates, last day not before the first, times as 24-hour `HH:MM`, a name),
and say why when they refuse. Routes: `/events/<id>/<approve|remove|restore>` (the old `reject`/`reopen` still work),
`/events/<id>/edit`, `/events/add`.

### Events feeds (a calendar published as RSS)

A feed whose type is `events` (Config page, "Parser") is handled by `event_feeds.py` instead of the article path:
no Reddit post is drafted, each item goes to the Events page as a *suggested* event. Built for Eden Prairie Local News
(`eplocalnews.org/events/feed/`, added 2026-11-19 as "Eden Prairie Local News: events"): an item's publish date is the
occurrence's start with a zone offset, and the event page carries schema.org data (end time, place name, street).
Rules: only upcoming occurrences; a recurring event shows once, as its next occurrence, and returns after it passes
(`storage.event_already_known`); an event dismissed with "Not an event" is never suggested again; text naming another
Minnesota town and never Eden Prairie is skipped and counted; at most 15 event pages are read per run, a second
apart; an unreadable page never loses the event; an end time not after the start (the site sends "00:00") is dropped.
The feed lists whatever is submitted to the paper's calendar, so promotional or commercial events appear (a "gold
buying event" did); the reviewer rejects them. Run by "Run pipeline now" with the other feeds.

### Stats: how our posts are doing (read-only)

`stats.py::refresh_stats()` snapshots, for every `posted` article that has a `reddit_post_id`, the score,
upvote ratio and comment count (`storage.record_stats()` -> `post_stats`, a history: a new row only when the
numbers moved or the last one is over an hour old), and saves up to 50 comments for posts under 14 days
old (`post_comments`, upserted by comment id so a re-run never duplicates). `storage.summarize_stats()` gives
the latest numbers and the 24-hour change shown on each Posted card; `/articles/<id>/stats` shows the
history and the comments. Triggered by the "Refresh stats" button or `python -m edenprairie_news.stats`.
`subreddit_sync` also records score/comments of every synced subreddit post into the same history.

It needs only the script app's **client id and secret** (`reddit_client.get_reddit_readonly()`, PRAW
read-only): no account logs in and nothing can post, vote or moderate. If an account is configured it is
used instead (same public data). Without the id/secret the button reports why on the page. **Not yet run
against live Reddit**: `fetch_post_stats()` / `fetch_comments()` are only exercised through fakes in the
tests, so the first real refresh is the real test.

### Events calendar: find, review, publish to the wiki

`events.py::extract_events()` reads an article's title + summary (all the tool stores) with plain rules
(stdlib only): month/day patterns (with optional weekday, `Dec. 5-7` ranges, ordinals, year inferred from the
article's publish date, past dates skipped), clock times and ranges (`6 to 8 p.m.`), and places from
`config/venues.yaml` (a starter list, extend it), street addresses, or an `at <Capitalised Phrase>`
guess (flagged "guessed"). A sentence counts as an event only with event wording or a clock time next to the date.
Unknown fields are left empty, never invented. `pipeline._suggest_events()` runs it for each new article and
stores `suggested` rows in `events` (a failure there is logged and never stops drafting).

Nothing reaches the public page unreviewed: the **Events** page (`/events`) lists suggestions to edit, approve
or reject, takes events typed by hand, and shows the exact wiki text from `wiki_page.render()` (approved,
not-yet-ended events grouped by month). **Update the wiki page** (`reddit_client.update_wiki`, setting
`reddit_wiki_page`, default `events`) needs a connected Reddit *account* allowed to edit the wiki (a moderator or
approved wiki editor) and the `wikiedit` scope -- accounts connected before this was added must reconnect on the
Config page. Without one the page shows the text to paste into the wiki editor. **Not yet run against real
articles or live Reddit**: it is tested on sample sentences, and only the title and feed summary are read, so an
event described only in the full article body is not seen. Known limit: a deadline ("registration opens Dec. 1")
looks like an event; the reviewer rejects or retitles it.

### Subreddit moderation view (separate domain from news drafting)

`subreddit_sync.py::sync_subreddit_posts()` is the orchestrator for this
domain, mirroring how `pipeline.py` orchestrates news drafting: it's the
only place that calls both `reddit_client` and `storage` together here.
Flow: `reddit_client.get_recent_submissions()` (recent live posts, not
modqueue) → `flag_rules.compute_flags()` per post → `storage.upsert_subreddit_post()`.

- `flag_rules.py` — the extension point for "what needs mod attention."
  Each rule is a `post dict -> flag string | None` function appended to
  `RULES`; `compute_flags()` runs them all. Ships with two starter rules
  (missing flair, has reports) to prove the pattern — add more here as
  moderation needs grow, without touching `subreddit_sync.py` or the web UI.
- `storage.subreddit_posts` table — `tags` (JSON list, mod-applied, e.g. via
  the web UI's "add tag" form) and `action_flags` (JSON list, recomputed
  every sync) are separate columns. `upsert_subreddit_post()` refreshes
  everything on a post except `tags` when re-syncing, so re-running sync
  never clobbers a mod's manual tagging.
- **Reserved tag: `"hidden"`.** `storage.get_subreddit_posts()` excludes
  any post tagged `"hidden"` unless called with `include_hidden=True`. The
  web UI's Hide/Unhide buttons just add/remove that one tag — there's no
  separate boolean column, so any other free-form tag (e.g.
  `"needs-followup"`) works the same way as a visible badge without needing
  its own schema change later.

### Config: DB-backed, editable from the web UI, `.env`/`feeds.yaml` as first-run seed only

`config.py`'s `get_reddit_config()` / `get_discord_config()` build a fresh
dataclass on every call: a `storage.settings` DB value if set and
non-empty, else the matching `.env` var. This is deliberate — it's what
lets the `/config` page's saves take effect on the very next pipeline run
or web request with **no process restart**. Don't reintroduce
module-import-time caching here (the old `RedditConfig`/`DiscordConfig`
classes worked that way and were replaced for this reason). `WebConfig`
(bind host/port) is the one exception, staying env-only — changing where
the process listens needs a restart regardless of storage, so there's no
reason to route it through the DB.

Call sites use `get_reddit_config().client_id` etc., not
`RedditConfig.client_id` — if you see the old class-attribute style
anywhere it's stale and should be updated to match.

The feed list works the same way but as a DB table instead of scalar
settings: `storage.list_feeds()` is the runtime source (used by
`pipeline.py`), not `config/feeds.yaml`. `config/feeds.yaml` is read
exactly once, by `storage._seed_feeds_if_empty()` inside `init_db()`, only
if the `feeds` table is empty — after that first run the DB is
authoritative and the YAML file is just a reference/example left in the
repo. Add/remove feeds via the web UI's `/config` page
(`storage.add_feed()`/`delete_feed()`), not by hand-editing the YAML.

`web/app.py` calls `storage.init_db()` once at module import time (not
per-request) specifically so routes like `/config` or `/modqueue` — which
don't happen to touch `articles`/`subreddit_posts` — can still assume the
`settings`/`feeds` tables already exist even if hit as the very first
request against a brand-new DB file.

### Reddit API policy

Reviewed against Reddit's **Data API Terms** (redditinc.com, last revised
2026-07-20) and **Moderator Code of Conduct** (redditinc.com, effective
2025-06-05) — both are JS-rendered SPAs that 403/fail for WebFetch and the
Chrome extension, but `curl` with a plain desktop browser User-Agent gets a
200 with the full text server-rendered in the HTML (just buried after a
large multi-language nav block). Neither document requires anything beyond
what's already in place: descriptive `REDDIT_USER_AGENT` (Data API Terms
§2.8, no masking user agent/OAuth identity), PRAW's built-in rate limiting
(§2.9/§3.2, no excessive/abusive usage), and the drafted→posted human
approval gate (§3.2, no spam/harassment; Mod CoC Rule 1, bots are subject
to the same Reddit Rules as manual actions). No code changes needed from
either doc. One open item, not urgent: Data API Terms §3.2 requires not
retaining data beyond the approved use case — `storage.py` persists
`articles`/`subreddit_posts` indefinitely with no expiry/deletion logic,
which is presumably fine (retention serves the tool's own moderation-assist
purpose) but has no explicit policy backing it if ever questioned.

Reddit's **Responsible Builder Policy** (support.reddithelp.com/hc/articles/42728983564564,
current as of "Updated 2 months ago" seen 2026-08-08) has now been read —
via Claude-in-Chrome, since it sits behind genuine bot-protection that
403s to curl even with a browser UA (don't retry curl/WebFetch on this
host; it needs a connected browser session). Findings:

- **No post-body bot-disclosure requirement exists anywhere** in this
  policy, the Data API Terms, or the Mod CoC. The speculative
  "bot-disclosure line in `formatter.py`'s post body" TODO from earlier
  versions of this doc was never confirmed and should be dropped — bot
  labeling is a Reddit-applied **App profile label**, tied to registering a
  developer profile (see below), not text the app itself has to add to a
  post.
- **Mixed-use account gap (flagged 2026-08-08, remediation tooling landed
  2026-08-08): in progress.** "App accounts should solely be used to
  perform app functions (no mixed use accounts)." `reddit_client.py`
  originally authenticated as the user's own personal
  moderator account — the same one used for manual moderation of
  r/edenprairie, not a dedicated bot account. The user now has a separate
  Reddit account intended for the subreddit/bot use. Code-side support for
  the cutover is in place: `reddit_client.get_oauth_authorize_url()` /
  `exchange_oauth_code()` implement a web-login OAuth flow (Config page's
  "Connect via Reddit login") so the dedicated account's password never has
  to be stored, `RedditSettings.is_configured` accepts either a refresh
  token or username/password, and `config.mod_queue_enabled()` (default
  off, `web/app.py`'s modqueue routes gate on it) means the dedicated
  account does *not* need to be a subreddit moderator just to post drafts —
  only check "Enable Mod Queue" if it's been added as one. What's still a
  user step, not something to do unilaterally: actually registering a
  script app under the dedicated account at reddit.com/prefs/apps (or
  reusing the existing `client_id`/`client_secret` if the same app can be
  repointed), running the Config page's "Connect via Reddit login" against
  it, and deciding whether that account gets invited as a moderator (Mod
  Queue) or stays posting-only. Flag this proactively if picking up further
  Reddit-integration work until the user confirms the live `.env`/DB
  settings have actually been switched over — landing the code isn't the
  same as completing the cutover.
- **Still unconfirmed**: *App registration* — "Apps must register and
  create a developer profile to get an App profile label." Unknown whether
  this tool's `client_id`/`client_secret` are tied to such a registration.
- **Unresolved, don't downplay this**: the policy's "Mod Tools" subsection
  states that a moderator's data access is granted solely for performing
  moderation actions, and that "all moderator tools are also subject to
  the Devvit App Review process" — worded as a requirement for mod tools
  generally, not just tools built on Devvit. This project performs
  moderation actions (drafted→posted posting, and the subreddit-moderation
  view's approve/remove flow) via a moderator account's API access, which
  is exactly what that subsection describes, even though it's a standalone
  Python/Flask script app, not a Devvit app (Devvit is a separate
  Node.js/TypeScript platform where apps run inside Reddit's own
  infrastructure, installed per-subreddit — adopting it would mean a full
  rewrite, not a dependency swap). The policy's "file a ticket if your use
  case isn't supported by Devvit" line reads more like a request-an-exception
  path than a blanket exemption. Net: it is genuinely unclear from the
  policy text alone whether this tool needs Devvit App Review or Reddit
  sign-off to stay compliant. Do not resolve this ambiguity by assumption —
  the user should ask Reddit directly via that ticket link.
- Everything else already reviewed still holds: descriptive
  `REDDIT_USER_AGENT` (transparency requirement, "must not misrepresent or
  mask how or why you are accessing Reddit data"), PRAW's rate limiting
  (excessive/abusive usage prohibition), and the drafted→posted human
  approval gate (spam/automated-posting prohibition) all satisfy this
  policy's requirements as written.

Separately, per Reddit's OAuth2 wiki (reddit-archive/reddit wiki), script
apps like this one authenticate via the password grant and technically
need to request explicit scopes (`identity`, `submit`, `modposts`,
`modflair`, `read`, etc.) — **PRAW abstracts this away**: initializing
`praw.Reddit()` with `client_id`/`client_secret`/`username`/`password` (as
`reddit_client.get_reddit()` does) makes PRAW request all scopes and
handle hourly token refresh automatically, so there's nothing to add here
for that. Confirmed current, no code changes needed.

### Planned: interactive Discord bot (not yet built)

The user wants richer Discord integration — slash commands and in-Discord
Approve/Reject buttons on draft messages — beyond the current webhook
notifier. That requires a `discord.py` bot with a persistent gateway
connection and its own bot token, which is a different operating model from
the rest of this tool (on-demand, no background process). This was
deliberately deferred as a phase 2 rather than bolted onto the webhook
notifier — when picking it up, it should probably live as its own
long-running entry point (e.g. `edenprairie_news/discord_bot.py` +
a console script) that calls into the same `storage.py`/`reddit_client.py`
functions the web UI uses, rather than duplicating pipeline logic.

## Scripts

Scripts marked **destructive** change or delete data, so confirm before running them. Scripts marked **sudo** need root. Scripts marked **launchd** or **cron** run on a schedule and are not normally run by hand.


- `python -m edenprairie_news.pipeline`: fetches feeds, drafts posts, then exits. Installed as `edenprairie-fetch`.
- `python -m edenprairie_news.web.app`: starts the mod review UI on port 1981. Installed as `edenprairie-web`.
- `pytest tests/`: tests. `scripts/` is empty.
