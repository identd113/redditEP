"""Local LAN web interface: review/edit drafts, approve+post, browse mod queue.

Binds to 0.0.0.0 (LAN-reachable) by default and has no auth of its own --
see README's security note. Set WEB_HOST=127.0.0.1 to restrict to this
machine only.
"""

import os
import re
import secrets

from flask import Flask, redirect, render_template, request, url_for

from datetime import date

from edenprairie_news import dates, matching, obituaries, reddit_client, reddit_link, reddit_public, stats, storage, wiki_page
from edenprairie_news.config import (WebConfig, get_discord_config, get_reddit_config, max_article_age_days,
                                     mod_queue_enabled)
from edenprairie_news.feed_parsers import PARSERS
from edenprairie_news.pipeline import run_pipeline
from edenprairie_news.storage import init_db
from edenprairie_news.subreddit_sync import sync_subreddit_posts
from edenprairie_news.web import help_texts

app = Flask(__name__)
init_db()  # once at process startup, so every route can assume the DB/tables exist


@app.template_filter("posted_when")
def posted_when(raw):
    """'Thu, Nov 19, 9:23 pm · 2 hours ago' for an article's publish date."""
    return dates.posted_label(raw)


@app.context_processor
def inject_feature_flags():
    return {"mod_queue_enabled": mod_queue_enabled(), "api_posting_enabled": get_reddit_config().is_configured,
            "button_help": {"exact": help_texts.EXACT, "prefix": help_texts.PREFIX}}


TABS = ("drafts", "sent", "posted", "subreddit", "removed")


@app.route("/")
def index():
    tab = request.args.get("tab", "drafts")
    if tab not in TABS:
        tab = "drafts"
    all_drafted = storage.get_by_status("drafted")
    show_obits = request.args.get("obits") == "1"
    obit_ids = {a.id for a in all_drafted if obituaries.is_obituary(a.title, a.summary, a.source)}
    if not show_obits:  # hidden, never deleted: the toggle brings them back
        all_drafted = [a for a in all_drafted if a.id not in obit_ids]
    # the source filter: one chip per feed, Eden Prairie's own feeds first, nearby cities after them
    counts: dict[str, list] = {}
    for a in all_drafted:
        entry = counts.setdefault(a.source, [0, a.scope == "related"])
        entry[0] += 1
    sources = sorted(((name, n, near) for name, (n, near) in counts.items()), key=lambda t: (t[2], -t[1], t[0]))
    source = request.args.get("source", "")
    shown = [a for a in all_drafted if a.source == source] if source in counts else all_drafted
    if source not in counts:
        source = ""
    drafted = [a for a in shown if a.scope != "related"]
    nearby = [a for a in shown if a.scope == "related"]
    sent = storage.get_by_status("sent")
    removed = storage.get_by_status("removed")
    posted = storage.get_by_status("posted")
    show_hidden = request.args.get("show_hidden") == "1"
    subreddit_posts = storage.get_subreddit_posts(include_hidden=show_hidden)
    post_stats = {a.reddit_post_id: storage.summarize_stats(storage.get_stats_history(a.reddit_post_id))
                  for a in posted if a.reddit_post_id} if tab == "posted" else {}
    subreddit = get_reddit_config().subreddit
    tabs = [("drafts", "Drafts", len(all_drafted)), ("sent", "Sent to Reddit", len(sent)), ("posted", "Posted", len(posted)),
            ("subreddit", f"r/{subreddit}", len(subreddit_posts)), ("removed", "Removed", len(removed))]
    return render_template(
        "index.html",
        tab=tab,
        tabs=tabs,
        sources=sources,
        source=source,
        subreddit=subreddit,
        drafted=drafted,
        nearby=nearby,
        show_obits=show_obits,
        obit_ids=obit_ids,
        sent=sent,
        removed=removed,
        posted=posted,
        post_stats=post_stats,
        subreddit_posts=subreddit_posts,
        show_hidden=show_hidden,
    )


@app.route("/pipeline/run", methods=["POST"])
def pipeline_run():
    summary = run_pipeline()
    return redirect(url_for("index", ran=1, tab="drafts", **summary))


@app.route("/subreddit/sync", methods=["POST"])
def subreddit_sync_route():
    """Read the newest posts in the subreddit. Needs the Reddit app details; without them (or when Reddit refuses)
    the page says so instead of showing an error."""
    try:
        summary = sync_subreddit_posts()
    except Exception as exc:
        return redirect(url_for("index", tab="subreddit", sync_error=f"{type(exc).__name__}: {exc}"[:300]))
    return redirect(url_for("index", tab="subreddit", synced=summary["synced"]))


@app.route("/subreddit-posts/<path:fullname>/tag", methods=["POST"])
def subreddit_post_tag(fullname):
    tag = request.form.get("tag", "").strip()
    if tag:
        storage.add_post_tag(fullname, tag)
    return redirect(url_for("index", show_hidden="1" if request.args.get("show_hidden") == "1" else "0"))


@app.route("/subreddit-posts/<path:fullname>/hide", methods=["POST"])
def subreddit_post_hide(fullname):
    storage.add_post_tag(fullname, "hidden")
    return redirect(url_for("index"))


@app.route("/subreddit-posts/<path:fullname>/unhide", methods=["POST"])
def subreddit_post_unhide(fullname):
    storage.remove_post_tag(fullname, "hidden")
    return redirect(url_for("index", show_hidden="1"))


@app.route("/articles/<int:article_id>")
def article_detail(article_id):
    article = storage.get_by_id(article_id)
    return render_template("article.html", article=article)


@app.route("/articles/<int:article_id>/edit", methods=["POST"])
def article_edit(article_id):
    storage.update_draft_text(
        article_id, request.form["post_title"], request.form["post_body"]
    )
    return redirect(url_for("article_detail", article_id=article_id))


@app.route("/articles/<int:article_id>/approve", methods=["POST"])
def article_approve(article_id):
    article = storage.get_by_id(article_id)
    reddit = reddit_client.get_reddit()
    if reddit_client.already_posted_on_reddit(reddit, article.url):
        storage.mark_removed(article_id)
        return redirect(url_for("index", duplicate=1))
    post_id = reddit_client.submit_post(reddit, article.post_title, article.post_body)
    storage.mark_posted(article_id, post_id)
    return redirect(url_for("index"))


@app.route("/articles/<int:article_id>/post")
def article_post_preview(article_id):
    """Step before Reddit: show any events found in this article (what, when, where, website, and how each would
    read on the wiki page) and let the person choose which go on the calendar."""
    article = storage.get_by_id(article_id)
    if article is None or article.status not in ("drafted", "sent"):
        return redirect(url_for("index"))
    if article.scope == "local":
        from edenprairie_news.pipeline import _suggest_events

        _suggest_events(article)  # fresh look at the text, in case the article was stored before events existed
    found = storage.get_events_for_article(article_id)
    return render_template(
        "post_confirm.html",
        article=article,
        found=[dict(e, preview=wiki_page.line(e), when=wiki_page.when_text(e)) for e in found],
        wiki_page_name=get_reddit_config().wiki_page,
        subreddit=get_reddit_config().subreddit,
        error=request.args.get("error", ""),
    )


def _apply_calendar_choices(article_id: int, form) -> str:
    """Approve (with any edits) the events the person ticked, and add a hand-typed one. Returns an error message,
    or '' when everything was accepted. Unticked suggestions are left as they are for the Events page."""
    known = {e["id"] for e in storage.get_events_for_article(article_id)}
    changes = []
    for raw_id in form.getlist("event_id"):
        if not raw_id.isdigit() or int(raw_id) not in known or form.get(f"add_{raw_id}") != "on":
            continue
        fields = {k: form.get(f"{k}_{raw_id}", "").strip()
                  for k in ("title", "start_date", "end_date", "start_time", "end_time", "location", "source_url")}
        try:
            date.fromisoformat(fields["start_date"])
            if fields["end_date"]:
                date.fromisoformat(fields["end_date"])
        except ValueError:
            return f"The date for \"{fields['title'] or 'an event'}\" is not valid; use year-month-day, for example 2026-11-21."
        changes.append((int(raw_id), fields))
    new_title = form.get("new_title", "").strip()
    new_event = None
    if new_title:
        try:
            date.fromisoformat(form.get("new_start_date", "").strip())
        except ValueError:
            return "The date for the event you typed is not valid; use year-month-day, for example 2026-11-21."
        new_event = (new_title, form.get("new_start_date").strip(), form.get("new_start_time", "").strip(),
                     form.get("new_end_time", "").strip(), form.get("new_location", "").strip(), form.get("new_source_url", "").strip())
    for event_id, fields in changes:  # nothing is changed until every date checked out
        storage.update_event(event_id, fields)
        storage.set_event_status(event_id, "approved")
    if new_event:
        storage.add_event(*new_event)
    return ""


@app.route("/articles/<int:article_id>/send", methods=["POST"])
def article_send(article_id):
    """One click: note that this draft went to Reddit, and open Reddit's own submit page with the
    subreddit, title and body already filled in. The person presses Post there, as themselves. When it comes
    from the preview page, the calendar choices made there are applied first."""
    article = storage.get_by_id(article_id)
    if article is None or article.status not in ("drafted", "sent"):
        return redirect(url_for("index"))
    if request.form.get("from_preview"):
        error = _apply_calendar_choices(article_id, request.form)
        if error:
            return redirect(url_for("article_post_preview", article_id=article_id, error=error))
    target = reddit_link.submit_url(get_reddit_config().subreddit, article.post_title, article.post_body)
    storage.mark_sent(article_id)
    return redirect(target, code=303)


@app.route("/articles/<int:article_id>/remove", methods=["POST"])
def article_remove(article_id):
    """Take a tile off the page for good. The link is remembered, so the pipeline will not add it again."""
    storage.mark_removed(article_id)
    return redirect(request.referrer or url_for("index"))


@app.route("/articles/<int:article_id>/restore", methods=["POST"])
def article_restore(article_id):
    storage.restore_removed(article_id)
    return redirect(request.referrer or url_for("index", tab="removed"))


@app.route("/articles/<int:article_id>/reopen", methods=["POST"])
def article_reopen(article_id):
    storage.reopen_draft(article_id)
    return redirect(url_for("index", tab="drafts"))


@app.route("/articles/<int:article_id>/link", methods=["POST"])
def article_link(article_id):
    """Paste the Reddit post's address to match it to this article by hand."""
    reddit_url = request.form.get("reddit_url", "").strip()
    if not reddit_link.post_id_from_url(reddit_url):
        return redirect(url_for("index", tab="sent", link_error=article_id))
    storage.link_posted(article_id, reddit_url)
    return redirect(url_for("index", tab="posted"))


@app.route("/stats/refresh", methods=["POST"])
def stats_refresh():
    """Read the current score, upvote ratio, comment count and comments of every posted article (read-only)."""
    try:
        summary = stats.refresh_stats()
    except Exception as exc:  # no credentials yet, Reddit refused, network down: say so on the page
        return redirect(url_for("index", tab="posted", stats_error=f"{type(exc).__name__}: {exc}"[:300]))
    return redirect(url_for("index", tab="posted", stats_tracked=summary["tracked"], stats_snapshots=summary["snapshots"],
                            stats_comments=summary["new_comments"], stats_removed=",".join(summary["removed"])))


@app.route("/articles/<int:article_id>/stats")
def article_stats(article_id):
    article = storage.get_by_id(article_id)
    if article is None or not article.reddit_post_id:
        return redirect(url_for("index"))
    history = storage.get_stats_history(article.reddit_post_id)
    return render_template(
        "stats.html",
        article=article,
        history=list(reversed(history)),
        summary=storage.summarize_stats(history),
        comments=storage.get_comments(article.reddit_post_id),
    )


@app.route("/events")
def events_page():
    approved = storage.get_events("approved")
    config = get_reddit_config()
    return render_template(
        "events.html",
        suggested=storage.get_events("suggested"),
        approved=[dict(e, preview=wiki_page.line(e)) for e in approved],
        removed=storage.get_events("rejected"),
        wiki_text=wiki_page.render(approved, date.today()),
        wiki_edit_url=f"https://www.reddit.com/r/{config.subreddit}/wiki/edit/{config.wiki_page}",
        wiki_page_name=config.wiki_page,
        subreddit=config.subreddit,
        today=date.today().isoformat(),
    )


@app.route("/events/<int:event_id>/<action>", methods=["POST"])
def event_action(event_id, action):
    # "reject"/"reopen" are the old names; the buttons now say Remove and Restore. A removed event is stored as
    # "rejected", which is what stops the events importer from suggesting it again.
    status = {"approve": "approved", "remove": "rejected", "reject": "rejected", "restore": "suggested", "reopen": "suggested"}.get(action)
    if status:
        storage.set_event_status(event_id, status)
    return redirect(url_for("events_page"))


def _event_problem(fields: dict) -> str:
    """Why these event fields cannot be saved, in plain words; '' when they are fine."""
    try:
        start = date.fromisoformat(fields.get("start_date", ""))
    except ValueError:
        return "The date is not valid; use year-month-day, for example 2026-11-21."
    if fields.get("end_date"):
        try:
            if date.fromisoformat(fields["end_date"]) < start:
                return "The last day is before the first day."
        except ValueError:
            return "The last day is not valid; use year-month-day, or leave it empty."
    for key, label in (("start_time", "start time"), ("end_time", "end time")):
        if fields.get(key) and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", fields[key]):
            return f"The {label} must look like 18:30 (24-hour), or be empty."
    if not fields.get("title"):
        return "An event needs a name."
    return ""


@app.route("/events/<int:event_id>/edit", methods=["POST"])
def event_edit(event_id):
    """Change any event: a suggestion, or one already on the calendar."""
    fields = {k: request.form.get(k, "").strip() for k in ("title", "start_date", "end_date", "start_time", "end_time", "location", "source_url")}
    problem = _event_problem(fields)
    if problem:
        return redirect(url_for("events_page", event_error=event_id, event_msg=problem))
    storage.update_event(event_id, fields)
    return redirect(url_for("events_page", saved=event_id))


@app.route("/events/add", methods=["POST"])
def event_add():
    fields = {k: request.form.get(k, "").strip() for k in ("title", "start_date", "start_time", "end_time", "location", "source_url")}
    problem = _event_problem(fields)
    if problem:
        return redirect(url_for("events_page", event_error="new", event_msg=problem))
    storage.add_event(fields["title"], fields["start_date"], fields["start_time"], fields["end_time"], fields["location"], fields["source_url"])
    return redirect(url_for("events_page"))


@app.route("/events/wiki", methods=["POST"])
def events_wiki():
    """Write the approved events to the subreddit's wiki page, when a Reddit account that may edit the wiki is
    connected. Without one the page shows the text to paste by hand."""
    config = get_reddit_config()
    if not config.is_configured:
        return redirect(url_for("events_page", wiki_error="No Reddit account is connected, so copy the text below into the wiki page yourself"))
    try:
        reddit_client.update_wiki(reddit_client.get_reddit(), config.wiki_page,
                                  wiki_page.render(storage.get_events("approved"), date.today()))
    except Exception as exc:  # not allowed to edit, token without the wiki scope, Reddit down: say so
        return redirect(url_for("events_page", wiki_error=f"{type(exc).__name__}: {exc}"[:300]))
    return redirect(url_for("events_page", wiki_ok=1))


@app.route("/reddit/match", methods=["POST"])
def reddit_match():
    """Look at the subreddit's newest posts (public feed, no key) and the synced ones, and link any
    that were made from a sent or drafted article."""
    config = get_reddit_config()
    try:
        posts = reddit_public.fetch_recent_posts(config.subreddit, config.user_agent)
    except reddit_public.RedditUnavailable as exc:
        posts, error = [], str(exc)
    else:
        error = ""
    posts += [dict(p, urls=[p["url"]] if p.get("url") else []) for p in storage.get_subreddit_posts(include_hidden=True)]
    matched = matching.match_posts(posts)
    return redirect(url_for("index", tab="sent", matched=len(matched), match_error=error))


@app.route("/modqueue")
def modqueue():
    if not mod_queue_enabled():
        return render_template("modqueue.html", items=[])
    reddit = reddit_client.get_reddit()
    items = reddit_client.get_mod_queue(reddit)
    return render_template("modqueue.html", items=items)


@app.route("/modqueue/<path:fullname>/approve", methods=["POST"])
def modqueue_approve(fullname):
    if not mod_queue_enabled():
        return redirect(url_for("modqueue"))
    reddit = reddit_client.get_reddit()
    reddit_client.approve(reddit, fullname)
    return redirect(url_for("modqueue"))


@app.route("/modqueue/<path:fullname>/remove", methods=["POST"])
def modqueue_remove(fullname):
    if not mod_queue_enabled():
        return redirect(url_for("modqueue"))
    reddit = reddit_client.get_reddit()
    reddit_client.remove(reddit, fullname, spam=request.form.get("spam") == "1")
    return redirect(url_for("modqueue"))


@app.route("/config")
def config_page():
    return render_template(
        "config.html",
        reddit_config=get_reddit_config(),
        reddit_redirect_uri=url_for("reddit_oauth_callback", _external=True),
        discord_config=get_discord_config(),
        feeds=storage.list_feeds(),
        parser_names=list(PARSERS.keys()),
        max_age_days=max_article_age_days(),
        stale_drafts=storage.count_drafts_older_than(max_article_age_days()),
        cleaned=request.args.get("cleaned"),
    )


@app.route("/config/reddit/oauth/start")
def reddit_oauth_start():
    reddit_config = get_reddit_config()
    if not (reddit_config.client_id and reddit_config.client_secret):
        return redirect(url_for("config_page", oauth_error="missing_client_credentials"))
    state = secrets.token_urlsafe(24)
    storage.set_setting("reddit_oauth_state", state)
    redirect_uri = url_for("reddit_oauth_callback", _external=True)
    authorize_url = reddit_client.get_oauth_authorize_url(redirect_uri, state)
    return redirect(authorize_url)


@app.route("/config/reddit/oauth/callback")
def reddit_oauth_callback():
    if request.args.get("error"):
        return redirect(url_for("config_page", oauth_error=request.args["error"]))
    expected_state = storage.get_setting("reddit_oauth_state")
    storage.set_setting("reddit_oauth_state", "")
    if not expected_state or request.args.get("state") != expected_state:
        return redirect(url_for("config_page", oauth_error="state_mismatch"))
    code = request.args.get("code")
    if not code:
        return redirect(url_for("config_page", oauth_error="missing_code"))
    redirect_uri = url_for("reddit_oauth_callback", _external=True)
    refresh_token = reddit_client.exchange_oauth_code(redirect_uri, code)
    storage.set_setting("reddit_refresh_token", refresh_token)
    return redirect(url_for("config_page", oauth_connected=1))


@app.route("/config/reddit", methods=["POST"])
def config_reddit():
    fields = {
        "client_id": "reddit_client_id",
        "client_secret": "reddit_client_secret",
        "username": "reddit_username",
        "password": "reddit_password",
        "user_agent": "reddit_user_agent",
        "subreddit": "reddit_subreddit",
        "sync_limit": "reddit_sync_limit",
    }
    for form_field, setting_key in fields.items():
        value = request.form.get(form_field, "").strip()
        if value:
            storage.set_setting(setting_key, value)
    storage.set_setting("mod_queue_enabled", "true" if request.form.get("mod_queue_enabled") == "on" else "false")
    return redirect(url_for("config_page"))


@app.route("/config/age", methods=["POST"])
def config_age():
    """How old an article may be (days since it was posted) and still be drafted. 0 means no limit."""
    raw = request.form.get("max_age_days", "").strip()
    if raw.isdigit():
        storage.set_setting("max_article_age_days", str(int(raw)))
    return redirect(url_for("config_page"))


@app.route("/config/age/cleanup", methods=["POST"])
def config_age_cleanup():
    """One-off: remove the drafts already stored that are older than the limit (they can be restored)."""
    removed = storage.remove_drafts_older_than(max_article_age_days())
    return redirect(url_for("config_page", cleaned=removed))


@app.route("/config/discord", methods=["POST"])
def config_discord():
    webhook_url = request.form.get("webhook_url", "").strip()
    if webhook_url:
        storage.set_setting("discord_webhook_url", webhook_url)
    return redirect(url_for("config_page"))


@app.route("/config/feeds/add", methods=["POST"])
def config_feeds_add():
    name = request.form.get("name", "").strip()
    url = request.form.get("url", "").strip()
    parser = request.form.get("parser", "default")
    tags = ["needs-filter"] if request.form.get("needs_filter") == "on" else []
    if request.form.get("related") == "on":
        tags.append("related")
    if name and url:
        storage.add_feed(name, url, tags, parser)
    return redirect(url_for("config_page"))


@app.route("/config/feeds/<int:feed_id>/delete", methods=["POST"])
def config_feeds_delete(feed_id):
    storage.delete_feed(feed_id)
    return redirect(url_for("config_page"))


def main() -> None:
    # Debug mode serves an interactive code console to anyone who can reach the port, and this app listens on the
    # whole LAN with no login, so it is off unless WEB_DEBUG=1 is set for local development.
    app.run(host=WebConfig.host, port=int(WebConfig.port), debug=os.environ.get("WEB_DEBUG") == "1")


if __name__ == "__main__":
    main()
