"""What each button does, in plain words. The page shows these behind a small "i" next to the button
(see base.html); a test makes sure no button in the templates is missing from here.

EXACT is looked up by the button's label (or its data-help-key, for the few labels used with two meanings, like
the Mod Queue's Approve and Remove, which act on Reddit itself). PREFIX covers labels with a number in them.
"""

EXACT = {
    # front page
    "Run pipeline now": "Fetches all your feeds, drafts a post for each new article (skipping links you have already seen or removed, and anything older than your age limit) and looks for events. It never posts anything to Reddit.",
    "Sync subreddit posts": "Reads the newest posts in r/edenprairie from Reddit so they show under 'Current subreddit stories'. Needs the Reddit app details on the Config page.",
    "Check Reddit for my posts": "Looks at the subreddit's public feed and matches any post made from an article you sent. If Reddit refuses, paste the post's address by hand under 'Sent to Reddit'.",
    "Refresh stats": "Reads the score, upvote ratio and comments of every article you posted, and keeps a history. Read-only; needs the Reddit app's Client ID and Secret.",
    "Post to Reddit": "Opens a preview first, where you can add any events found in the article to the calendar. Then Reddit opens in a new tab with the post filled in, and you press Post there, as yourself.",
    "Post with the API": "Posts straight to Reddit as the connected account, without opening Reddit. Only shown when a Reddit account is connected.",
    "Remove": "Takes this off every list for good. The link is remembered, so it will not be drafted again. You can bring it back from the 'Removed' list at the bottom. Nothing changes on Reddit.",
    "Restore": "Brings a removed article back: to Posted if it had been posted, otherwise to the drafts.",
    "Link": "Paste the Reddit post's address into the box, then press this to match the post to this article.",
    "Open Reddit again": "Opens Reddit's pre-filled submit page for this article again, in case you closed it without posting.",
    "Not posted, back to drafts": "You never posted this one: puts it back among the drafts.",
    "Add tag": "Adds your own label to this subreddit post, for sorting. Only seen in this tool.",
    "Hide": "Hides this subreddit post from 'Current subreddit stories' (this tool's view only). 'Show hidden posts' or Unhide brings it back. Nothing changes on Reddit.",
    "Unhide": "Puts this subreddit post back in the list.",
    # editing a draft
    "Save changes": "Saves your edits to this item. Nothing is sent to Reddit.",
    # events
    "Approve": "Puts this event on the calendar, meaning the wiki page text. You can still change it later.",
    "Remove event": "Takes this event off the calendar and the review list for good. It will not be suggested again. Restore it from 'Removed events' at the bottom. Nothing changes on Reddit until you update the wiki page.",
    "Restore event": "Puts this removed event back in the review list.",
    "Back to review": "Takes this event off the calendar and back to the review list, without removing it.",
    "Add as approved": "Adds the event you typed straight to the calendar.",
    "Update the wiki page": "Writes the approved, upcoming events to the subreddit's wiki page. Needs a connected Reddit account that may edit the wiki; otherwise copy the text below and paste it into the wiki editor yourself.",
    # settings
    "Save": "Saves how many days old an article may be and still be drafted. 0 means no limit.",
    "Save Reddit settings": "Saves the Reddit details above. A blank box keeps what is already saved.",
    "Connect via Reddit login": "Sends you to Reddit to sign in and allow this tool, so your password is never stored here. Save the Client ID and Secret first.",
    "Save Discord webhook": "Saves the Discord address that gets a message when new drafts are ready.",
    "Add feed": "Adds this feed to the list the pipeline reads the next time it runs.",
    "Delete": "Removes this feed from the list. Articles already drafted from it stay.",
    # Mod Queue: these act on Reddit itself
    "Reddit: Approve": "Approves this post or comment on Reddit, which clears it from the mod queue. This acts on Reddit itself.",
    "Reddit: Remove": "Removes this post or comment from the subreddit on Reddit. This acts on Reddit itself, and is not the same as Remove on the drafts page.",
    "Reddit: Remove as spam": "Removes this on Reddit and marks it as spam. This acts on Reddit itself.",
}

PREFIX = {
    "Remove the ": "Removes the drafts already stored that are older than your age limit. They go to the 'Removed' list and can be restored. Posted and sent articles are not touched.",
}
