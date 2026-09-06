#!/usr/bin/env python3
r"""
main.py — The ONE script for your whole Substack stats pipeline. Pulls
post stats, Notes stats, subscriber stats, comments, and traffic sources,
then builds a local dashboard and opens it in your browser automatically.

FIRST-TIME SETUP: just run it.
    python main.py
The first time you run this, it looks in your cookie file for the
publication subdomain and numeric user ID that the Chrome extension
copies alongside the session cookie. If those are there, setup is
automatic. If not, it walks you through a short interactive prompt
and saves your answers so every run after that skips straight to
pulling your real data. See "Substack App - Setup & Usage Guide.md"
for the full walkthrough.

Cookies expire periodically (days to weeks). If the script starts
erroring with HTTP 401/403, get a fresh one the same way you did the
first time (the Chrome extension makes this a one-click refresh).

THREE WAYS TO REFRESH:

1. Full historical pull (the default):
     python main.py
   Pulls everything — all posts, all notes back to your first real one,
   all comments, all subscribers. Slowest, most thorough.

2. Dashboard only, no new data (or double-click "Substack App - Run Dashboard.bat"):
     python main.py --dashboard-only
   (or the short form: python main.py -d)
   Just rebuilds dashboard.html from what's already in the database —
   useful after changing a chart or just wanting another look. Doesn't
   even need a valid cookie, since it only reads your local database.

3. Recent-window pull (or double-click one of the "Refresh Last N Days" files):
     python main.py --recent 7
     python main.py --recent 14
     python main.py --recent 30
   (or the short form: python main.py -r 7)
   Only refreshes posts/notes/comments published or posted in the last
   N days — much faster than a full pull, since old notes especially
   involve grinding through hundreds of pages that rarely change engagement-
   wise. Posts/notes outside the window aren't touched at all this run;
   their existing data from your last full pull stays exactly as it was.
   Subscribers always pull in full regardless (it's already fast).
"""

import os
import shutil
import sys
import csv
import json
import sqlite3
import time
import webbrowser
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ==================== FIRST-RUN SETUP WIZARD ====================
CONFIG_PATH = "substack_app_config.json"
# Cookie file lives outside any cloud-synced folder. The Chrome
# extension copies a JSON bundle (cookie + subdomain + user ID) here;
# older files that contain only the raw cookie string still work.
COOKIE_FILE_PATH = os.path.expanduser("~/.substack_cookie.txt")


def normalize_publication(value):
    """Turn a URL or hostname into the publication subdomain, or None."""
    if value is None:
        return None
    raw = str(value).strip()
    raw = raw.replace("https://", "").replace("http://", "")
    raw = raw.split(".substack.com")[0].split("/")[0].split(":")[0].strip()
    reserved = {"", "www", "open", "on", "support", "substack.com"}
    if raw.lower() in reserved:
        return None
    return raw or None


def parse_session_bundle(raw):
    """Parse a cookie file / env-var payload.

    Accepts the Chrome extension's JSON bundle::

        {"publication": "example", "user_id": "123", "cookie": "..."}

    or a legacy raw cookie string. Returns a dict with cookie,
    publication, and user_id (each None when missing).
    """
    result = {"cookie": None, "publication": None, "user_id": None}
    if raw is None:
        return result
    text = raw.strip()
    if not text:
        return result

    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            result["cookie"] = text
            return result
        if isinstance(data, dict) and (
            "cookie" in data or "publication" in data or "subdomain" in data or "user_id" in data
        ):
            cookie = data.get("cookie")
            if isinstance(cookie, str) and cookie.strip():
                result["cookie"] = cookie.strip()
            publication = normalize_publication(
                data.get("publication") or data.get("subdomain")
            )
            if publication:
                result["publication"] = publication
            user_id = data.get("user_id")
            if user_id is not None and str(user_id).strip().isdigit():
                result["user_id"] = str(user_id).strip()
            return result

    result["cookie"] = text
    return result


def read_session_bundle():
    """Load the session bundle from SUBSTACK_COOKIE or the cookie file."""
    env_cookie = os.environ.get("SUBSTACK_COOKIE")
    if env_cookie:
        return parse_session_bundle(env_cookie)
    if os.path.exists(COOKIE_FILE_PATH):
        try:
            with open(COOKIE_FILE_PATH, "r", encoding="utf-8") as f:
                content = f.read()
            return parse_session_bundle(content)
        except OSError:
            pass
    return parse_session_bundle(None)


def get_cookie():
    """Return the cookie string, checking env var first, then the file."""
    return read_session_bundle().get("cookie")


def save_config(publication, user_id):
    config = {"publication": publication, "user_id": str(user_id)}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def run_setup_wizard(prefill=None):
    """
    Interactive one-time setup, run automatically the first time this
    script is used (whenever substack_app_config.json doesn't exist yet
    and the cookie file doesn't already contain both values).
    Collects your publication subdomain and your numeric Substack user
    ID, and saves them so this never has to run again.
    """
    prefill = prefill or {}
    print("=" * 60)
    print("FIRST-TIME SETUP")
    print("=" * 60)
    print()
    print(f"This only happens once — your answers are saved to '{CONFIG_PATH}'")
    print("in this same folder, and every run after this skips straight to")
    print("pulling your real data.")
    print()

    publication = normalize_publication(prefill.get("publication"))
    if publication:
        print(f"1. Subdomain (from your cookie file): {publication}.substack.com")
        print()
    else:
        print("1. What's your Substack publication's subdomain?")
        print("   This is the part before '.substack.com' in your own Substack's")
        print("   web address. If your Substack is at https://example.substack.com,")
        print("   enter: example")
        print()
        print("   The Chrome extension now copies this for you — if you re-copy")
        print("   your session and paste it into the cookie file, you can skip")
        print("   typing it here next time.")
        print()
        while not publication:
            raw = input("   Your subdomain: ").strip()
            publication = normalize_publication(raw)
            if not publication:
                print("   That didn't look right — please enter just the subdomain part.")
        print(f"   Got it: {publication}.substack.com")
        print()

    user_id = prefill.get("user_id")
    if user_id is not None:
        user_id = str(user_id).strip()
        if not user_id.isdigit():
            user_id = None
    if user_id:
        print(f"2. User ID (from your cookie file): {user_id}")
        print()
    else:
        print("2. What's your numeric Substack user ID?")
        print("   This is a number, not your name or handle. Fastest way to find")
        print("   it is to use the Chrome extension included in this folder,")
        print("   which now copies it with your cookie. If you'd rather look it")
        print("   up yourself:")
        print()
        print("   - Go to substack.com/notes, logged in as yourself")
        print("   - Open DevTools (press F12) -> Network tab -> filter 'Fetch/XHR'")
        print("   - Refresh the page")
        print("   - Look for a request whose name starts with 'profile/' followed")
        print("     by a number, e.g. 'profile/123456789'")
        print("   - That number is your user ID")
        print()
        print("   (Full step-by-step screenshots are in the Setup & Usage guide")
        print("   if you'd rather follow along there.)")
        print()
        while not user_id:
            raw = input("   Your numeric user ID: ").strip()
            if raw.isdigit():
                user_id = raw
            else:
                print("   That should be digits only, no letters or symbols — try again.")

    save_config(publication, user_id)

    print()
    print(f"Saved. Publication: {publication}.substack.com | User ID: {user_id}")
    print()
    if not get_cookie():
        print("One more thing before your first real pull will work: you'll need")
        print("a session cookie. The easiest way is the Chrome extension included")
        print("in this folder ('Substack App - Cookie Extension') — see the Setup")
        print("& Usage guide for the two-minute install. Once that's done, just")
        print("run this script again.")
        print()
    return publication, user_id


def load_config():
    """Loads publication + user ID from the saved config file, the cookie
    file / SUBSTACK_COOKIE bundle, or the one-time setup wizard."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if saved.get("publication") and saved.get("user_id"):
                return saved["publication"], saved["user_id"]
        except (json.JSONDecodeError, KeyError):
            pass  # fall through if the file got corrupted

    bundle = read_session_bundle()
    if bundle.get("publication") and bundle.get("user_id"):
        save_config(bundle["publication"], bundle["user_id"])
        print(
            f"Using publication and user ID from your cookie file: "
            f"{bundle['publication']}.substack.com | {bundle['user_id']}"
        )
        print()
        return bundle["publication"], bundle["user_id"]

    return run_setup_wizard(prefill=bundle)


# ==================== CONFIGURATION ====================
OUTPUT_DIR = "output"
DB_PATH = os.path.join(OUTPUT_DIR, "substack_history.db")
DASHBOARD_PATH = os.path.join(OUTPUT_DIR, "dashboard.html")

FETCH_OWN_OPENS = True          # posts: look up your own opens per post
OWN_OPENS_MAX_PAGES = 10        # safety cap: 200 recipients per post
OWN_OPENS_DELAY_SECONDS = 0.4

FETCH_TRAFFIC = True             # posts: look up traffic-source breakdown per post
TRAFFIC_DELAY_SECONDS = 0.4

FETCH_IMPRESSIONS = True        # notes: look up impressions per note
IMPRESSIONS_DELAY_SECONDS = 0.4

FETCH_SUBSCRIBERS = True        # pull full subscriber list for stats
SUBSCRIBERS_PAGE_SIZE = 50       # UNVERIFIED guess at page size — matches
                                   # the offset/limit convention used by
                                   # other endpoints on this publication
SUBSCRIBERS_MAX_PAGES = 20       # safety cap: 1000 subscribers
SUBSCRIBERS_DELAY_SECONDS = 0.4

FETCH_COMMENTS = True            # pull reader comments on your posts
COMMENTS_DELAY_SECONDS = 0.4      # one extra request per post, same
                                    # politeness pattern as own-opens/
                                    # impressions
COMMENTS_LIMIT_PER_POST = 200     # UNVERIFIED cap — see fetch_post_comments()
# --- IMPORTANT: the comments feature below (endpoint, response shape,
# and pagination) was built from public documentation of Substack's API
# found via web search — NOT verified against this account, since this
# environment can't reach substack.com directly. If it errors or comes
# back empty, that's expected until confirmed for real; see the comments
# on fetch_post_comments() for what to check.

# Subscriber name and email ARE stored (changed from an earlier default
# of aggregate-only, at explicit user request). This data — and the
# generated dashboard.html containing it — lives inside a cloud-synced
# folder, same as everything else in this project.
# =========================================================


def print_no_cookie_error():
    print("ERROR: No Substack cookie found.")
    print()
    print("Option A — environment variable:")
    print("  Windows (PowerShell): $env:SUBSTACK_COOKIE = \"paste it here\"")
    print("  macOS/Linux:          export SUBSTACK_COOKIE='paste it here'")
    print()
    print(f"Option B — save it to a file (needed for unattended/scheduled runs):")
    print(f"  {COOKIE_FILE_PATH}")
    print()
    print("Use the Chrome extension to copy your session (cookie, subdomain,")
    print("and user ID) and paste that into the file.")


PUBLICATION, OWN_USER_ID = load_config()

BASE_PUB = f"https://{PUBLICATION}.substack.com"
BASE_GLOBAL = "https://substack.com"
COOKIE = get_cookie()  # may be None — only required if actually pulling from Substack

HEADERS = {
    "Cookie": COOKIE,
    "User-Agent": "Mozilla/5.0 (compatible; personal-stats-script/1.0)",
    "Accept": "application/json",
}



# ==================== POSTS ====================
def get_json_pub(path, params=None):
    """GET a JSON endpoint on your own publication, using your session cookie."""
    url = f"{BASE_PUB}{path}"
    if params:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{query}"
    req = Request(url, headers=HEADERS)
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        print(f"  [!] HTTP {e.code} on {path} — cookie may be expired, or endpoint changed.")
        return None
    except URLError as e:
        print(f"  [!] Network error on {path}: {e.reason}")
        return None
    except json.JSONDecodeError:
        print(f"  [!] Non-JSON response on {path} — likely a login redirect (cookie expired?).")
        return None


def post_json_pub(path, body):
    """
    POST a JSON body to an endpoint on your own publication. Some
    endpoints (confirmed: subscriber-stats) take their filters/pagination
    as a JSON POST body rather than query params — captured directly
    from a real browser request via "Copy as cURL" in DevTools.
    """
    url = f"{BASE_PUB}{path}"
    data = json.dumps(body).encode("utf-8")
    headers = dict(HEADERS)
    headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        print(f"  [!] HTTP {e.code} on {path} — cookie may be expired, or endpoint changed.")
        return None
    except URLError as e:
        print(f"  [!] Network error on {path}: {e.reason}")
        return None
    except json.JSONDecodeError:
        print(f"  [!] Non-JSON response on {path} — likely a login redirect (cookie expired?).")
        return None


def fetch_post_stats(limit=500):
    """
    Pull per-post stats (views, engagement, etc.) — this is the same endpoint
    that powers the "All posts" table on your Stats > Posts page.
    """
    print("Fetching post stats...")
    posts = []
    offset = 0
    page_size = 20  # matches what the dashboard itself uses
    while offset < limit:
        data = get_json_pub("/api/v1/publication/stats/email_stats", params={
            "offset": offset,
            "limit": page_size,
            "order_by": "post_date",
            "order_direction": "desc",
        })
        if not data:
            break
        # Response shape wasn't fully confirmed — handle both a bare list
        # and a dict wrapping a list under a likely key.
        if isinstance(data, list):
            batch = data
        else:
            batch = data.get("rows") or data.get("posts") or data.get("results") or data.get("data") or []
            if not batch and isinstance(data, dict):
                # Unknown shape — save it raw so nothing is lost, and stop.
                print("  [!] Unexpected response shape. Dumping raw JSON to output/raw_email_stats.json for inspection.")
                os.makedirs(OUTPUT_DIR, exist_ok=True)
                with open(os.path.join(OUTPUT_DIR, "raw_email_stats.json"), "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                break
        if not batch:
            break
        posts.extend(batch)
        offset += page_size
        if len(batch) < page_size:
            break
    print(f"  -> {len(posts)} posts found")
    return posts


def fetch_post_comments(post_id, post_url):
    """
    Pull reader comments left on a specific post.

    ENDPOINT: GET {publication}/api/v1/post/{post_id}/comments
    Source of this pattern: an actual working open-source Substack MCP
    server (glama.ai/mcp/servers/conorbronsdon/substack-mcp), corroborated
    independently by a blog post from someone who separately reverse-
    engineered a paired "archive" + "comments" endpoint set for Substack
    (matthagy.substack.com/p/developing-a-custom-substack-front). NOT
    verified against this specific account — built from public research
    only, since this environment can't reach substack.com directly.

    RESPONSE SHAPE (per the same source): a list of comment objects with
    id, body, name, date, user_id, reactions, children_count. This
    function tries a few reasonable wrapper-key guesses ("comments",
    "results", or a bare list) since the exact wrapper key wasn't shown
    in the source. If this comes back empty or errors, the real shape
    needs confirming via DevTools — visit a post's comments page
    ({post_url}/comments), open Network/Fetch-XHR, and look for the
    request that loads the comment list.

    LINK per comment: no confirmed per-comment deep-link format was
    found, so this links to the post's comments page as a whole
    ({post_url}/comments — confirmed as a real, live URL pattern via
    two independent examples), not a specific highlighted comment.
    """
    data = get_json_pub(f"/api/v1/post/{post_id}/comments", params={"limit": COMMENTS_LIMIT_PER_POST})
    if not data:
        return []

    if isinstance(data, list):
        raw_comments = data
    else:
        raw_comments = data.get("comments") or data.get("results") or data.get("data") or []

    comments = []
    for c in raw_comments:
        reactions = c.get("reactions")
        if isinstance(reactions, dict):
            reaction_count = sum(v for v in reactions.values() if isinstance(v, (int, float)))
        else:
            reaction_count = c.get("reaction_count") or 0

        comments.append({
            "comment_id": c.get("id"),
            "post_id": post_id,
            "commenter_name": c.get("name") or c.get("author") or "Unknown",
            "body": c.get("body") or "",
            "date": c.get("date"),
            "reaction_count": reaction_count,
            "children_count": c.get("children_count") or 0,
            "comment_url": c.get("permalink") or f"{post_url}/comments",
        })
    return comments


def fetch_own_opens(post_id, max_pages=OWN_OPENS_MAX_PAGES):
    """
    Search a post's recipient list for your own row (matched by
    OWN_USER_ID) and return your "opens" count for that post, or None
    if your row wasn't found within max_pages (either you never opened
    it, or it's buried further down than we searched).

    This is a genuinely different metric than "views" — it's specifically
    email/app opens tied to your own subscriber account, not a general
    self-view estimate. Ordered by opens descending, so if you're a
    frequent opener of your own posts (likely), your row tends to surface
    within the first page or two.
    """
    for page in range(max_pages):
        offset = page * 20
        data = get_json_pub(f"/api/v1/post_management/detail/{post_id}/recipients", params={
            "offset": offset,
            "limit": 20,
            "order_by": "opens",
            "order_direction": "desc",
        })
        if not data:
            return None
        rows = data.get("rows", [])
        if not rows:
            return None  # ran out of recipients, you weren't in the list
        for row in rows:
            if str(row.get("user_id")) == OWN_USER_ID:
                return row.get("opens")
        if len(rows) < 20:
            return None  # last page, you're not a recipient of this post
        time.sleep(OWN_OPENS_DELAY_SECONDS)
    return None  # exceeded max_pages without finding your row


def fetch_post_traffic(post_id):
    """
    Pull the traffic-source breakdown for a specific post (Email, Direct,
    Social, etc.) — the same category breakdown shown in Substack's own
    "Traffic sources" panel on a post's stats page.

    ENDPOINT: GET {publication}/api/v1/post_management/detail/{post_id}/traffic

    CONFIDENCE: higher than most of this project's newer features — this
    follows the exact same /api/v1/post_management/detail/{post_id}/...
    prefix as the /recipients endpoint, which IS fully confirmed working
    on this account. This specific /traffic sub-path itself was captured
    directly from a real DevTools response earlier in this project (for
    "The Four Capacities We Build"), showing this exact shape:
        {"referrers": [...], "devices": [...],
         "categories": [{"category_type": "Direct", "category_views": 48, ...}, ...]}
    Only the "categories" list is used here — a clean, already-aggregated
    Email/Direct/Social breakdown, rather than re-deriving it from the
    more granular "referrers" list ourselves.
    """
    data = get_json_pub(f"/api/v1/post_management/detail/{post_id}/traffic")
    if not data:
        return []
    categories = data.get("categories", [])
    return [
        {"category": c.get("category_type"), "views": c.get("category_views") or c.get("view_count") or 0}
        for c in categories
        if c.get("category_type")
    ]


def init_posts_db(conn):
    """
    Create the history table if it doesn't exist yet.
    Known fields get real columns (so you can query/sort/chart on them
    directly); anything unexpected is preserved in raw_json so nothing
    is ever silently lost even if Substack adds/renames fields later.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS post_stats_history (
            run_timestamp TEXT NOT NULL,
            post_id INTEGER NOT NULL,
            title TEXT,
            post_date TEXT,
            audience TEXT,
            type TEXT,
            section_name TEXT,
            tags TEXT,
            bylines TEXT,
            queued INTEGER,
            sent INTEGER,
            delivered INTEGER,
            dropped INTEGER,
            opens INTEGER,
            opened INTEGER,
            open_rate REAL,
            clicks INTEGER,
            clicked INTEGER,
            click_through_rate REAL,
            signups INTEGER,
            subscribes INTEGER,
            free_to_paid_upgrades INTEGER,
            unsubscribes INTEGER,
            likes INTEGER,
            comments INTEGER,
            shares INTEGER,
            restacks INTEGER,
            engagement_rate REAL,
            unique_engagements INTEGER,
            subscribers_finished_post INTEGER,
            views INTEGER,
            video_views INTEGER,
            video_minutes_watched INTEGER,
            downloads INTEGER,
            your_own_opens INTEGER,
            raw_json TEXT,
            PRIMARY KEY (run_timestamp, post_id)
        )
    """)
    conn.commit()
    _migrate_post_columns(conn)


def _migrate_post_columns(conn):
    """
    If this database was created by an earlier version of this script
    (before some column existed), add any missing columns now instead
    of erroring on insert. Safe to run every time — does nothing if
    the table is already up to date.
    """
    cur = conn.execute("PRAGMA table_info(post_stats_history)")
    existing = {row[1] for row in cur.fetchall()}
    all_needed = KNOWN_COLUMNS + ["raw_json"]
    added = []
    for col in all_needed:
        if col not in existing:
            col_type = "TEXT" if col in ("raw_json", "title", "post_date", "audience",
                                          "type", "section_name", "tags", "bylines") else "INTEGER"
            conn.execute(f"ALTER TABLE post_stats_history ADD COLUMN {col} {col_type}")
            added.append(col)
    if added:
        conn.commit()
        print(f"  (upgraded database: added new column(s) {', '.join(added)})")


KNOWN_COLUMNS = [
    "title", "post_date", "audience", "type", "section_name", "tags", "bylines",
    "queued", "sent", "delivered", "dropped", "opens", "opened", "open_rate",
    "clicks", "clicked", "click_through_rate", "signups", "subscribes",
    "free_to_paid_upgrades", "unsubscribes", "likes", "comments", "shares",
    "restacks", "engagement_rate", "unique_engagements",
    "subscribers_finished_post", "views", "video_views",
    "video_minutes_watched", "downloads", "your_own_opens",
]


def save_post_snapshot(conn, posts, run_timestamp):
    """Insert one row per post for this run. Never overwrites past runs."""
    rows_written = 0
    for p in posts:
        values = [run_timestamp, p.get("post_id")]
        values += [p.get(col) for col in KNOWN_COLUMNS]
        values.append(json.dumps(p))
        placeholders = ", ".join("?" for _ in values)
        columns = ", ".join(["run_timestamp", "post_id"] + KNOWN_COLUMNS + ["raw_json"])
        try:
            conn.execute(f"INSERT INTO post_stats_history ({columns}) VALUES ({placeholders})", values)
            rows_written += 1
        except sqlite3.IntegrityError:
            # Already have a snapshot for this post at this exact timestamp
            # (e.g. script re-run in the same minute) — skip, don't duplicate.
            pass
    conn.commit()
    return rows_written


def export_latest_posts_csv(conn, path):
    """Convenience export: the most recent snapshot of every post, one row each."""
    cur = conn.execute("""
        SELECT h.* FROM post_stats_history h
        INNER JOIN (
            SELECT post_id, MAX(run_timestamp) AS max_run
            FROM post_stats_history GROUP BY post_id
        ) latest ON h.post_id = latest.post_id AND h.run_timestamp = latest.max_run
        ORDER BY h.post_date DESC
    """)
    columns = [d[0] for d in cur.description]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(cur.fetchall())


def export_full_posts_history_csv(conn, path):
    """Every snapshot ever taken, for charting trends over time later."""
    cur = conn.execute("SELECT * FROM post_stats_history ORDER BY post_id, run_timestamp")
    columns = [d[0] for d in cur.description]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(cur.fetchall())



# ==================== NOTES ====================
def get_json_global(path, params=None):
    url = f"{BASE_GLOBAL}{path}"
    if params:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{query}"
    req = Request(url, headers=HEADERS)
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        print(f"  [!] HTTP {e.code} on {path} — cookie may be expired, or endpoint changed.")
        return None
    except URLError as e:
        print(f"  [!] Network error on {path}: {e.reason}")
        return None
    except json.JSONDecodeError:
        print(f"  [!] Non-JSON response on {path} — likely a login redirect (cookie expired?).")
        return None


NOTES_MAX_PAGES = 400  # safety backstop only — in practice, fetch_notes()
                        # now stops automatically once it reaches
                        # NOTES_EARLIEST_REAL_DATE (see below), so this
                        # cap should rarely if ever actually bind. Raised
                        # from 30, which was cutting off history at only
                        # ~3 months back instead of reaching full history.

NOTES_EARLIEST_REAL_DATE = "2023-01-01"  # entries dated before this are
    # almost certainly migration/share artifacts, not real notes — e.g.
    # sharing an old published post as a note can pick up that POST's
    # original publish date instead of the note's real posting date.
    # This is a generic safety floor (Substack Notes didn't exist before
    # early 2023), not a personal date — if you notice a real early note
    # of yours getting filtered out, move this earlier; if you still see
    # obviously-wrong ancient dates on notes, move it later to match your
    # own account's actual first real note.


def categorize_note(comment):
    """
    Categorize a note by its content type, based on the real attachment
    types confirmed in this account's actual data:
      - no attachments -> "Text"
      - attachment type "post" -> "Shares a post"
      - attachment type "image" -> "Image"
      - attachment type "link" -> "Link"
      - attachment type "comment" -> "Reply to a comment" (confirmed by
        inspecting real examples: these wrap a quoted comment from
        someone else's post thread, with your own reply as the body —
        not a restack of a note, despite the field name suggesting that)
    If a note somehow has multiple attachment types, the first one found
    wins — real examples so far only ever show one attachment per note.
    """
    attachments = comment.get("attachments") or []
    if not attachments:
        return "Text"
    type_labels = {
        "post": "Shares a post",
        "image": "Image",
        "link": "Link",
        "comment": "Reply to a comment",
    }
    first_type = attachments[0].get("type")
    return type_labels.get(first_type, f"Other ({first_type})")


def fetch_notes(max_pages=NOTES_MAX_PAGES, stop_at_date=None):
    """
    Pull your own notes with engagement stats. Dedupes by note id and
    filters out other people's notes that appear via restack context.

    Stops automatically once it reaches stop_at_date (defaults to
    NOTES_EARLIEST_REAL_DATE, a generic safety floor — i.e. full history),
    with a small buffer of extra pages afterward in case items aren't
    perfectly chronological within a page. Pass a more recent date (e.g.
    7/14/30 days ago) for a fast recent-window refresh instead of grinding
    through hundreds of pages of full history every time.
    """
    if stop_at_date is None:
        stop_at_date = NOTES_EARLIEST_REAL_DATE

    print("Fetching notes...")
    notes_by_id = {}  # dedupe by comment id, keep richest version
    cursor = None
    page = 0
    seen_cursors = set()
    pages_past_target = 0
    BUFFER_PAGES_AFTER_TARGET = 3  # keep going a few more pages past the
                                     # target date, in case of minor
                                     # out-of-order items within a page

    while page < max_pages:
        params = {}
        if cursor:
            # UNVERIFIED: guessing the param name is "cursor". If pagination
            # doesn't work, check a real "load more" request in DevTools —
            # see TROUBLESHOOTING at the bottom of this file.
            params["cursor"] = cursor

        data = get_json_global(f"/api/v1/reader/feed/profile/{OWN_USER_ID}", params=params or None)
        if not data:
            break

        items = data.get("items", [])
        if not items:
            break

        page_min_date = None
        for item in items:
            comment = item.get("comment")
            if not comment:
                continue
            if str(comment.get("user_id")) != OWN_USER_ID:
                continue  # someone else's note, appeared via restack context
            note_id = comment.get("id")
            if note_id is None:
                continue
            # Keep the version with the most complete reaction data
            # (some duplicate entries show slightly different counts
            # depending on which context they appeared under).
            existing = notes_by_id.get(note_id)
            if existing is None or (comment.get("reaction_count", 0) >= existing.get("reaction_count", 0)):
                comment["note_type"] = categorize_note(comment)
                notes_by_id[note_id] = comment
            note_date = (comment.get("date") or "")[:10]
            if note_date and (page_min_date is None or note_date < page_min_date):
                page_min_date = note_date

        page += 1
        if page % 15 == 0:
            print(f"  ...page {page}, {len(notes_by_id)} notes so far"
                  + (f" (back to {page_min_date})" if page_min_date else ""))

        if page_min_date and page_min_date <= stop_at_date:
            pages_past_target += 1
            if pages_past_target >= BUFFER_PAGES_AFTER_TARGET:
                print(f"  -> reached target date ({stop_at_date}) with "
                      f"{BUFFER_PAGES_AFTER_TARGET}-page buffer, stopping pagination early")
                break

        next_cursor = data.get("nextCursor")
        if not next_cursor or next_cursor == cursor:
            break
        if next_cursor in seen_cursors:
            # We've seen this exact cursor before — pagination isn't
            # actually advancing, we'd loop forever. Stop here.
            print(f"  [!] Cursor repeated after {page} page(s) — pagination may not be")
            print("      working correctly. See TROUBLESHOOTING at the bottom of this file.")
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    notes = list(notes_by_id.values())

    # Drop anything older than stop_at_date. For a full pull this is
    # NOTES_EARLIEST_REAL_DATE, filtering out old post-share date
    # artifacts (see that constant's comment for why). For a recent-
    # window pull this is the requested cutoff (e.g. 7/14/30 days ago),
    # so this also correctly restricts results to just that window.
    before_filter = len(notes)
    notes = [n for n in notes if (n.get("date") or "9999")[:10] >= stop_at_date]
    filtered_out = before_filter - len(notes)

    if notes:
        dates = sorted(n.get("date", "") for n in notes if n.get("date"))
        oldest, newest = dates[0][:10], dates[-1][:10]
        print(f"  -> {len(notes)} of your own notes found across {page} page(s)")
        print(f"     date range covered: {oldest} to {newest}")
        if filtered_out:
            print(f"     (filtered out {filtered_out} entr{'y' if filtered_out == 1 else 'ies'} dated before "
                  f"{stop_at_date})")
    else:
        print(f"  -> 0 of your own notes found across {page} page(s)")
    return notes


def fetch_note_impressions(note_id):
    """
    Look up the impressions count for a single note from its stats page
    (the same data shown under the "Impressions" chart when you view a
    note's own stats page on Substack). Returns the number, or None if
    it couldn't be found.
    """
    entity_key = f"c-{note_id}"
    data = get_json_global(f"/api/v1/note_stats/{entity_key}")
    if not data:
        return None
    for card in data.get("cards", []):
        if card.get("cardId") == "impressions":
            headers = card.get("headers", [])
            if headers:
                return headers[0].get("value")
    return None


def init_notes_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS note_stats_history (
            run_timestamp TEXT NOT NULL,
            note_id INTEGER NOT NULL,
            date TEXT,
            body TEXT,
            reaction_count INTEGER,
            restacks INTEGER,
            children_count INTEGER,
            impressions INTEGER,
            note_type TEXT,
            edited_at TEXT,
            raw_json TEXT,
            PRIMARY KEY (run_timestamp, note_id)
        )
    """)
    conn.commit()
    _migrate_notes_columns(conn)


def _migrate_notes_columns(conn):
    """
    If this database was created by an earlier version of this script
    (before some column existed), add it now instead of erroring on
    insert. Safe to run every time.
    """
    cur = conn.execute("PRAGMA table_info(note_stats_history)")
    existing = {row[1] for row in cur.fetchall()}
    for col, col_type in [("impressions", "INTEGER"), ("note_type", "TEXT")]:
        if col not in existing:
            conn.execute(f"ALTER TABLE note_stats_history ADD COLUMN {col} {col_type}")
            conn.commit()
            print(f"  (upgraded database: added new column {col})")


def save_note_snapshot(conn, notes, run_timestamp):
    rows_written = 0
    for n in notes:
        values = [
            run_timestamp,
            n.get("id"),
            n.get("date"),
            n.get("body"),
            n.get("reaction_count"),
            n.get("restacks"),
            n.get("children_count"),
            n.get("impressions"),
            n.get("note_type"),
            n.get("edited_at"),
            json.dumps(n),
        ]
        placeholders = ", ".join("?" for _ in values)
        columns = "run_timestamp, note_id, date, body, reaction_count, restacks, children_count, impressions, note_type, edited_at, raw_json"
        try:
            conn.execute(f"INSERT INTO note_stats_history ({columns}) VALUES ({placeholders})", values)
            rows_written += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return rows_written


def export_latest_notes_csv(conn, path):
    cur = conn.execute("""
        SELECT h.* FROM note_stats_history h
        INNER JOIN (
            SELECT note_id, MAX(run_timestamp) AS max_run
            FROM note_stats_history GROUP BY note_id
        ) latest ON h.note_id = latest.note_id AND h.run_timestamp = latest.max_run
        ORDER BY h.date DESC
    """)
    columns = [d[0] for d in cur.description]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(cur.fetchall())


def export_full_notes_history_csv(conn, path):
    cur = conn.execute("SELECT * FROM note_stats_history ORDER BY note_id, run_timestamp")
    columns = [d[0] for d in cur.description]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(cur.fetchall())


# ==================== TRAFFIC SOURCES ====================
def init_traffic_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS post_traffic_history (
            run_timestamp TEXT NOT NULL,
            post_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            views INTEGER,
            PRIMARY KEY (run_timestamp, post_id, category)
        )
    """)
    conn.commit()


def save_traffic_snapshot(conn, post_id, categories, run_timestamp):
    rows_written = 0
    for c in categories:
        category = c.get("category")
        if not category:
            continue
        try:
            conn.execute(
                "INSERT INTO post_traffic_history (run_timestamp, post_id, category, views) VALUES (?, ?, ?, ?)",
                (run_timestamp, post_id, category, c.get("views") or 0),
            )
            rows_written += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return rows_written


def get_latest_traffic_by_post(conn):
    """Returns {post_id_str: {category: views}} using each post's most
    recent traffic snapshot."""
    try:
        cur = conn.execute("""
            SELECT h.post_id, h.category, h.views FROM post_traffic_history h
            INNER JOIN (
                SELECT post_id, MAX(run_timestamp) AS max_run
                FROM post_traffic_history GROUP BY post_id
            ) latest ON h.post_id = latest.post_id AND h.run_timestamp = latest.max_run
        """)
        result = {}
        for post_id, category, views in cur.fetchall():
            result.setdefault(str(post_id), {})[category] = views
        return result
    except sqlite3.OperationalError:
        return {}


# ==================== COMMENTS ====================
def init_comments_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS comment_stats_history (
            run_timestamp TEXT NOT NULL,
            comment_id INTEGER NOT NULL,
            post_id INTEGER,
            post_title TEXT,
            commenter_name TEXT,
            body TEXT,
            date TEXT,
            reaction_count INTEGER,
            children_count INTEGER,
            comment_url TEXT,
            raw_json TEXT,
            PRIMARY KEY (run_timestamp, comment_id)
        )
    """)
    conn.commit()


def save_comment_snapshot(conn, comments, run_timestamp):
    rows_written = 0
    for c in comments:
        values = [
            run_timestamp,
            c.get("comment_id"),
            c.get("post_id"),
            c.get("post_title"),
            c.get("commenter_name"),
            c.get("body"),
            c.get("date"),
            c.get("reaction_count"),
            c.get("children_count"),
            c.get("comment_url"),
            json.dumps(c),
        ]
        placeholders = ", ".join("?" for _ in values)
        columns = ("run_timestamp, comment_id, post_id, post_title, commenter_name, body, date, "
                   "reaction_count, children_count, comment_url, raw_json")
        try:
            conn.execute(f"INSERT INTO comment_stats_history ({columns}) VALUES ({placeholders})", values)
            rows_written += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return rows_written


def get_latest_comments(conn):
    try:
        cur = conn.execute("""
            SELECT h.* FROM comment_stats_history h
            INNER JOIN (
                SELECT comment_id, MAX(run_timestamp) AS max_run
                FROM comment_stats_history GROUP BY comment_id
            ) latest ON h.comment_id = latest.comment_id AND h.run_timestamp = latest.max_run
            ORDER BY h.date DESC
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    except sqlite3.OperationalError:
        return []


def export_latest_comments_csv(conn, path):
    cur = conn.execute("""
        SELECT h.* FROM comment_stats_history h
        INNER JOIN (
            SELECT comment_id, MAX(run_timestamp) AS max_run
            FROM comment_stats_history GROUP BY comment_id
        ) latest ON h.comment_id = latest.comment_id AND h.run_timestamp = latest.max_run
        ORDER BY h.date DESC
    """)
    columns = [d[0] for d in cur.description]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(cur.fetchall())


# ==================== SUBSCRIBERS ====================
def fetch_subscribers(max_pages=SUBSCRIBERS_MAX_PAGES):
    """
    Pull your full subscriber list from the publication's subscriber
    CRM endpoint. Name and email ARE saved (see save_subscriber_snapshot)
    — this was a deliberate later change at the user's request; earlier
    versions of this script excluded them by default. user_photo_url is
    still not saved (no use case for it).

    CONFIRMED via "Copy as cURL" from a real browser request: this is a
    POST with a JSON body, not a GET with query params — that's why the
    earlier GET-based attempts all 404'd regardless of what params were
    tried. Pagination happens via "offset" inside the body.
    """
    print("Fetching subscribers...")
    subs_by_id = {}
    offset = 0
    expected_total = None

    for page in range(max_pages):
        body = {
            "filters": {"order_by_desc_nulls_last": "subscription_created_at"},
            "limit": SUBSCRIBERS_PAGE_SIZE,
            "offset": offset,
            "includeTags": True,
        }
        data = post_json_pub("/api/v1/subscriber-stats", body)
        if not data:
            break
        if expected_total is None:
            expected_total = data.get("count")

        batch = data.get("subscribers", [])
        if not batch:
            break

        for s in batch:
            sub_id = s.get("subscription_id")
            if sub_id is not None:
                subs_by_id[sub_id] = s

        offset += len(batch)
        time.sleep(SUBSCRIBERS_DELAY_SECONDS)

        if len(batch) < SUBSCRIBERS_PAGE_SIZE:
            break
        if expected_total is not None and len(subs_by_id) >= expected_total:
            break

    subs = list(subs_by_id.values())
    if expected_total:
        print(f"  -> {len(subs)} subscribers found (publication reports {expected_total} total)")
        if len(subs) < expected_total:
            print(f"  [!] Only got {len(subs)}/{expected_total} — pagination may need")
            print("      re-verifying via DevTools on your Subscribers dashboard page.")
    else:
        print(f"  -> {len(subs)} subscribers found")
    return subs


def init_subscribers_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriber_stats_history (
            run_timestamp TEXT NOT NULL,
            subscription_id INTEGER NOT NULL,
            subscription_created_at TEXT,
            subscription_type TEXT,
            subscription_interval TEXT,
            is_subscribed INTEGER,
            is_founding INTEGER,
            is_gift INTEGER,
            is_comp INTEGER,
            is_free_trial INTEGER,
            is_bitcoin INTEGER,
            activity_rating INTEGER,
            total_revenue_generated REAL,
            name TEXT,
            email TEXT,
            PRIMARY KEY (run_timestamp, subscription_id)
        )
    """)
    conn.commit()
    _migrate_subscriber_columns(conn)


def _migrate_subscriber_columns(conn):
    """If this database predates name/email being stored, add those
    columns now instead of erroring on insert."""
    cur = conn.execute("PRAGMA table_info(subscriber_stats_history)")
    existing = {row[1] for row in cur.fetchall()}
    added = []
    for col in ("name", "email"):
        if col not in existing:
            conn.execute(f"ALTER TABLE subscriber_stats_history ADD COLUMN {col} TEXT")
            added.append(col)
    if added:
        conn.commit()
        print(f"  (upgraded database: added new column(s) {', '.join(added)})")


def save_subscriber_snapshot(conn, subs, run_timestamp):
    """
    Saves subscriber name and email alongside the aggregate fields —
    this is a deliberate choice (not the default from earlier in this
    project), made explicitly at the user's request. Note this means
    subscriber contact info now lives in dashboard.html and the local
    database, both inside a cloud-synced folder.
    """
    rows_written = 0
    for s in subs:
        values = [
            run_timestamp,
            s.get("subscription_id"),
            s.get("subscription_created_at"),
            s.get("subscription_type"),
            s.get("subscription_interval"),
            s.get("is_subscribed"),
            s.get("is_founding"),
            s.get("is_gift"),
            s.get("is_comp"),
            s.get("is_free_trial"),
            s.get("is_bitcoin"),
            s.get("activity_rating"),
            s.get("total_revenue_generated"),
            s.get("user_name"),
            s.get("user_email_address"),
        ]
        placeholders = ", ".join("?" for _ in values)
        columns = ("run_timestamp, subscription_id, subscription_created_at, subscription_type, "
                   "subscription_interval, is_subscribed, is_founding, is_gift, is_comp, "
                   "is_free_trial, is_bitcoin, activity_rating, total_revenue_generated, name, email")
        try:
            conn.execute(f"INSERT INTO subscriber_stats_history ({columns}) VALUES ({placeholders})", values)
            rows_written += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return rows_written


def export_latest_subscribers_csv(conn, path):
    cur = conn.execute("""
        SELECT h.* FROM subscriber_stats_history h
        INNER JOIN (
            SELECT MAX(run_timestamp) AS max_run FROM subscriber_stats_history
        ) latest ON h.run_timestamp = latest.max_run
        ORDER BY h.subscription_created_at DESC
    """)
    columns = [d[0] for d in cur.description]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(cur.fetchall())


# ==================== DASHBOARD ====================
def get_latest_posts(conn):
    try:
        cur = conn.execute("""
            SELECT h.* FROM post_stats_history h
            INNER JOIN (
                SELECT post_id, MAX(run_timestamp) AS max_run
                FROM post_stats_history GROUP BY post_id
            ) latest ON h.post_id = latest.post_id AND h.run_timestamp = latest.max_run
            ORDER BY h.post_date DESC
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    except sqlite3.OperationalError:
        return []  # table doesn't exist yet — no posts pulled yet, that's fine


def get_latest_notes(conn):
    try:
        cur = conn.execute("""
            SELECT h.* FROM note_stats_history h
            INNER JOIN (
                SELECT note_id, MAX(run_timestamp) AS max_run
                FROM note_stats_history GROUP BY note_id
            ) latest ON h.note_id = latest.note_id AND h.run_timestamp = latest.max_run
            ORDER BY h.date DESC
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    except sqlite3.OperationalError:
        return []  # table doesn't exist yet — no notes pulled yet, that's fine


def get_posts_trend(conn):
    """
    Total views/opens across all posts, one point per real calendar DATE
    — e.g. "August 1: 1,240 total views". If you run the pull script more
    than once on the same day, only the latest run of that day is used,
    since views/opens are cumulative totals already; summing multiple
    same-day pulls would double-count. For an individual post's own
    history over time, click that post's row in the table instead —
    this chart is the all-posts-combined total.
    """
    try:
        cur = conn.execute("""
            SELECT run_timestamp, SUM(views) as total_views, SUM(opens) as total_opens,
                   SUM(likes) as total_likes, AVG(open_rate) as avg_open_rate
            FROM post_stats_history GROUP BY run_timestamp ORDER BY run_timestamp
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    except sqlite3.OperationalError:
        return []

    # Collapse to one point per calendar date. Rows are already ordered
    # ascending by run_timestamp, so later same-day rows simply overwrite
    # earlier ones here, leaving the latest run of each day.
    by_date = {}
    for r in rows:
        date_key = (r["run_timestamp"] or "")[:10]
        by_date[date_key] = {**r, "run_timestamp": date_key}
    return [by_date[d] for d in sorted(by_date.keys())]


def get_notes_trend(conn):
    """
    Total reactions/impressions across all notes, one point per real
    calendar DATE — same fix as get_posts_trend above. If you run the
    pull script more than once on the same day, only the latest run of
    that day is used, since these are cumulative totals already; summing
    multiple same-day pulls would double-count. For an individual note's
    own history over time, click that note's row in the table instead.
    """
    try:
        cur = conn.execute("""
            SELECT run_timestamp, SUM(reaction_count) as total_reactions,
                   SUM(restacks) as total_restacks, SUM(impressions) as total_impressions
            FROM note_stats_history GROUP BY run_timestamp ORDER BY run_timestamp
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    except sqlite3.OperationalError:
        return []

    by_date = {}
    for r in rows:
        date_key = (r["run_timestamp"] or "")[:10]
        by_date[date_key] = {**r, "run_timestamp": date_key}
    return [by_date[d] for d in sorted(by_date.keys())]


def get_post_history_by_id(conn):
    """
    Every snapshot ever saved for every post, grouped by post_id — this
    is what powers the click-to-drill-down detail view. One point per
    real calendar DATE, using the latest run of that day (same fix as
    get_posts_trend — otherwise running the pull script several times in
    one day shows as several flat, misleading points instead of one).
    """
    try:
        cur = conn.execute("""
            SELECT post_id, run_timestamp, views, opens, open_rate, likes, your_own_opens
            FROM post_stats_history ORDER BY post_id, run_timestamp
        """)
    except sqlite3.OperationalError:
        return {}
    by_post_date = {}
    for post_id, run_timestamp, views, opens, open_rate, likes, your_own_opens in cur.fetchall():
        key = str(post_id)
        date_key = (run_timestamp or "")[:10]
        by_post_date.setdefault(key, {})[date_key] = {
            "run_timestamp": date_key,
            "views": views or 0,
            "opens": opens or 0,
            "open_rate": round((open_rate or 0) * 100, 1),
            "likes": likes or 0,
            "your_own_opens": your_own_opens,
        }
    return {
        post_id: [by_date[d] for d in sorted(by_date.keys())]
        for post_id, by_date in by_post_date.items()
    }


def get_note_history_by_id(conn):
    """Same idea as get_post_history_by_id, for notes."""
    try:
        cur = conn.execute("""
            SELECT note_id, run_timestamp, reaction_count, impressions, restacks
            FROM note_stats_history ORDER BY note_id, run_timestamp
        """)
    except sqlite3.OperationalError:
        return {}
    by_note_date = {}
    for note_id, run_timestamp, reaction_count, impressions, restacks in cur.fetchall():
        key = str(note_id)
        date_key = (run_timestamp or "")[:10]
        by_note_date.setdefault(key, {})[date_key] = {
            "run_timestamp": date_key,
            "reactions": reaction_count or 0,
            "impressions": impressions or 0,
            "restacks": restacks or 0,
        }
    return {
        note_id: [by_date[d] for d in sorted(by_date.keys())]
        for note_id, by_date in by_note_date.items()
    }


def get_latest_subscribers(conn):
    try:
        cur = conn.execute("""
            SELECT h.* FROM subscriber_stats_history h
            INNER JOIN (
                SELECT MAX(run_timestamp) AS max_run FROM subscriber_stats_history
            ) latest ON h.run_timestamp = latest.max_run
            ORDER BY h.subscription_created_at DESC
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    except sqlite3.OperationalError:
        return []  # table doesn't exist yet — no subscribers pulled yet, that's fine


def compute_subscriber_growth(subs):
    """
    Reconstruct a cumulative growth curve from individual signup dates —
    this works even from a single pull, since every subscriber record
    carries its own historical signup timestamp. Bucketed by month.
    """
    from collections import Counter
    months = sorted(Counter((s.get("subscription_created_at") or "")[:7] for s in subs
                             if s.get("subscription_created_at")).items())
    labels, new_counts, cumulative = [], [], []
    running = 0
    for month, count in months:
        running += count
        labels.append(month)
        new_counts.append(count)
        cumulative.append(running)
    return {"labels": labels, "new": new_counts, "cumulative": cumulative}


def compute_posts_activity_by_month(posts):
    """
    Same idea as compute_notes_activity_by_month, for posts: views/opens
    grouped by the post's own publish month — "which months' posts
    performed well" — distinct from the calendar-date trend chart, which
    answers "what were the combined totals on a given real date."
    """
    from collections import defaultdict
    views_by_month = defaultdict(int)
    opens_by_month = defaultdict(int)
    count_by_month = defaultdict(int)

    for p in posts:
        month = (p.get("post_date") or "")[:7]
        if not month:
            continue
        views_by_month[month] += p.get("views") or 0
        opens_by_month[month] += p.get("opens") or 0
        count_by_month[month] += 1

    months = sorted(count_by_month.keys())
    return {
        "labels": months,
        "views": [views_by_month[m] for m in months],
        "opens": [opens_by_month[m] for m in months],
        "post_count": [count_by_month[m] for m in months],
    }


def compute_notes_by_type(notes):
    """
    Breakdown of your notes by content type (Text, Shares a post, Image,
    Link, Reply to a comment — see categorize_note() for how these are
    determined from real attachment data). Includes average reactions
    and impressions per type, so you can see which kind of note tends
    to perform best, not just how many of each you've posted.
    """
    from collections import defaultdict
    counts = defaultdict(int)
    reactions_sum = defaultdict(int)
    impressions_sum = defaultdict(int)

    for n in notes:
        note_type = n.get("note_type") or "Unknown"
        counts[note_type] += 1
        reactions_sum[note_type] += n.get("reaction_count") or 0
        impressions_sum[note_type] += n.get("impressions") or 0

    # Sort by count, most common first
    types = sorted(counts.keys(), key=lambda t: counts[t], reverse=True)
    return {
        "labels": types,
        "counts": [counts[t] for t in types],
        "avg_reactions": [round(reactions_sum[t] / counts[t], 1) if counts[t] else 0 for t in types],
        "avg_impressions": [round(impressions_sum[t] / counts[t], 1) if counts[t] else 0 for t in types],
    }


def compute_notes_activity_by_month(notes):
    """
    Reconstruct reactions/impressions by the month each note was actually
    POSTED, not by when you happened to run the pull script — same idea
    as compute_subscriber_growth. Works from a single pull. This is a
    genuinely different (and more useful) question than the per-run
    trend: "did notes posted in a given month perform well" rather than
    "did the running totals across all notes grow between two check-ins."
    """
    from collections import defaultdict
    reactions_by_month = defaultdict(int)
    impressions_by_month = defaultdict(int)
    count_by_month = defaultdict(int)

    for n in notes:
        month = (n.get("date") or "")[:7]
        if not month:
            continue
        reactions_by_month[month] += n.get("reaction_count") or 0
        impressions_by_month[month] += n.get("impressions") or 0
        count_by_month[month] += 1

    months = sorted(count_by_month.keys())
    return {
        "labels": months,
        "reactions": [reactions_by_month[m] for m in months],
        "impressions": [impressions_by_month[m] for m in months],
        "note_count": [count_by_month[m] for m in months],
    }


def slugify_title(title):
    """
    Construct a Substack post URL slug from its title. Inferred from 4
    real examples (confirmed working):
      "The risk of leading" -> the-risk-of-leading
      "The Jedi and the sensei" -> the-jedi-and-the-sensei
      "The Four Capacities We Build" -> the-four-capacities-we-build
      "Practice Journal - Issue 2" -> practice-journal-issue-2
    Pattern: lowercase, any run of non-alphanumeric characters collapses
    to a single hyphen, trimmed at both ends.

    NOT guaranteed for every title — this is inferred, not a confirmed
    API field. Titles with apostrophes, em-dashes, or other unusual
    punctuation could theoretically slugify differently than Substack's
    real internal logic, and if two posts would produce the same slug,
    Substack may append a suffix we have no way to predict. If a
    generated link 404s, that's the likely cause.
    """
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return slug


def safe_num(v, default=0):
    return v if isinstance(v, (int, float)) else default


def get_pull_log(conn):
    """
    Every distinct pull ever recorded, with how many posts/notes/
    subscribers were captured in that specific run — powers the Log tab.
    A run that only partially succeeded (e.g. subscribers 404'd) still
    shows up, just with 0 in that column.
    """
    counts = {}
    table_map = [("post_stats_history", "posts"), ("note_stats_history", "notes"),
                 ("subscriber_stats_history", "subscribers")]
    for table, key in table_map:
        try:
            cur = conn.execute(f"SELECT run_timestamp, COUNT(*) FROM {table} GROUP BY run_timestamp")
            for ts, n in cur.fetchall():
                if not ts:
                    continue
                counts.setdefault(ts, {"posts": 0, "notes": 0, "subscribers": 0})[key] = n
        except sqlite3.OperationalError:
            pass
    log = [{"timestamp": ts, **c} for ts, c in counts.items()]
    log.sort(key=lambda r: r["timestamp"], reverse=True)
    return log


def get_recent_pull_timestamps(conn, limit=2):
    """
    Distinct run timestamps across all three tables, most recent first.
    Pulled from all three (not just posts) in case a given run only
    partially succeeded — e.g. posts and notes worked but subscribers
    404'd, that run should still count as a real pull.
    """
    timestamps = set()
    for table in ("post_stats_history", "note_stats_history", "subscriber_stats_history"):
        try:
            cur = conn.execute(f"SELECT DISTINCT run_timestamp FROM {table}")
            timestamps.update(row[0] for row in cur.fetchall() if row[0])
        except sqlite3.OperationalError:
            pass
    return sorted(timestamps, reverse=True)[:limit]


def build_dashboard():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found.")
        print("This should not happen when running via main.py — the posts/notes")
        print("pull steps above should have created it. Check for errors above.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    posts = get_latest_posts(conn)
    notes = get_latest_notes(conn)
    comments = get_latest_comments(conn)
    posts_trend = get_posts_trend(conn)
    notes_trend = get_notes_trend(conn)
    subscribers = get_latest_subscribers(conn)
    post_history = get_post_history_by_id(conn)
    post_traffic_by_id = get_latest_traffic_by_post(conn)
    note_history = get_note_history_by_id(conn)
    recent_pulls = get_recent_pull_timestamps(conn)
    pull_log = get_pull_log(conn)
    conn.close()

    if not posts and not notes and not subscribers:
        print("Database exists but has no data yet. Run the pull scripts first.")
        sys.exit(1)

    # ---- KPI calculations ----
    total_posts = len(posts)
    total_views = sum(safe_num(p.get("views")) for p in posts)
    total_own_opens = sum(safe_num(p.get("your_own_opens")) for p in posts)
    open_rates = [p.get("open_rate") for p in posts if isinstance(p.get("open_rate"), (int, float))]
    avg_open_rate = (sum(open_rates) / len(open_rates)) if open_rates else 0
    total_notes = len(notes)
    total_reactions = sum(safe_num(n.get("reaction_count")) for n in notes)
    total_impressions = sum(safe_num(n.get("impressions")) for n in notes)
    avg_reactions = (total_reactions / total_notes) if total_notes else 0

    total_subscribers = len(subscribers)
    founding_count = sum(1 for s in subscribers if s.get("is_founding"))
    comp_count = sum(1 for s in subscribers if s.get("is_comp"))
    gift_count = sum(1 for s in subscribers if s.get("is_gift"))
    free_trial_count = sum(1 for s in subscribers if s.get("is_free_trial"))
    paid_count = sum(1 for s in subscribers
                      if s.get("subscription_interval") not in (None, "free") and not s.get("is_comp") and not s.get("is_gift"))
    activity_ratings = [s.get("activity_rating") for s in subscribers if isinstance(s.get("activity_rating"), (int, float))]
    avg_activity = (sum(activity_ratings) / len(activity_ratings)) if activity_ratings else 0
    total_revenue = sum(safe_num(s.get("total_revenue_generated")) for s in subscribers)
    subscriber_growth = compute_subscriber_growth(subscribers)
    notes_activity_by_month = compute_notes_activity_by_month(notes)
    notes_by_type = compute_notes_by_type(notes)
    posts_activity_by_month = compute_posts_activity_by_month(posts)

    def subscriber_type_label(s):
        if s.get("is_founding"):
            return "Founding"
        if s.get("is_comp"):
            return "Comp"
        if s.get("is_gift"):
            return "Gift"
        if s.get("is_free_trial"):
            return "Free trial"
        if s.get("subscription_interval") not in (None, "free"):
            return "Paid"
        return "Free"

    # Top 10 posts by views/opens, top 10 notes by reactions/impressions — for the bar charts
    top_posts = sorted(posts, key=lambda p: safe_num(p.get("views")), reverse=True)[:10]
    top_posts_by_opens = sorted(posts, key=lambda p: safe_num(p.get("opens")), reverse=True)[:10]
    top_notes = sorted(notes, key=lambda n: safe_num(n.get("reaction_count")), reverse=True)[:10]
    top_notes_by_impressions = sorted(notes, key=lambda n: safe_num(n.get("impressions")), reverse=True)[:10]

    def note_label(body):
        body = (body or "").replace("\n", " ").strip()
        return (body[:50] + "…") if len(body) > 50 else body

    # Overall traffic-source aggregate: sum each category's views across
    # every post's latest traffic snapshot.
    overall_traffic_totals = {}
    for post_id_str, categories in post_traffic_by_id.items():
        for category, views in categories.items():
            overall_traffic_totals[category] = overall_traffic_totals.get(category, 0) + (views or 0)
    overall_traffic_sorted = sorted(overall_traffic_totals.items(), key=lambda kv: kv[1], reverse=True)

    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "current_pull": recent_pulls[0] if len(recent_pulls) > 0 else None,
        "previous_pull": recent_pulls[1] if len(recent_pulls) > 1 else None,
        "pull_log_table": [
            {
                "date": r["timestamp"][:10] if r["timestamp"] else "",
                "timestamp": r["timestamp"],
                "posts": r["posts"],
                "notes": r["notes"],
                "subscribers": r["subscribers"],
            }
            for r in pull_log
        ],
        "comments_table": [
            {
                "date": (c.get("date") or "")[:10],
                "post_title": c.get("post_title") or "",
                "commenter_name": c.get("commenter_name") or "",
                "body": (lambda b: (b[:120] + "…") if b and len(b) > 120 else (b or ""))(c.get("body")),
                "reactions": safe_num(c.get("reaction_count")),
                "replies": safe_num(c.get("children_count")),
                "url": c.get("comment_url") or "",
            }
            for c in comments
        ],
        "kpis": {
            "total_posts": total_posts,
            "total_views": total_views,
            "total_own_opens": total_own_opens,
            "avg_open_rate": round(avg_open_rate * 100, 1),
            "total_notes": total_notes,
            "total_reactions": total_reactions,
            "total_impressions": total_impressions,
            "avg_reactions": round(avg_reactions, 1),
            "total_subscribers": total_subscribers,
            "founding_count": founding_count,
            "comp_count": comp_count,
            "gift_count": gift_count,
            "free_trial_count": free_trial_count,
            "paid_count": paid_count,
            "avg_activity": round(avg_activity, 1),
            "total_revenue": round(total_revenue, 2),
        },
        "top_posts_chart": {
            "labels": [(p.get("title") or "")[:35] for p in top_posts],
            "views": [safe_num(p.get("views")) for p in top_posts],
        },
        "top_posts_opens_chart": {
            "labels": [(p.get("title") or "")[:35] for p in top_posts_by_opens],
            "opens": [safe_num(p.get("opens")) for p in top_posts_by_opens],
        },
        "top_notes_chart": {
            "labels": [note_label(n.get("body")) for n in top_notes],
            "reactions": [safe_num(n.get("reaction_count")) for n in top_notes],
        },
        "top_notes_impressions_chart": {
            "labels": [note_label(n.get("body")) for n in top_notes_by_impressions],
            "impressions": [safe_num(n.get("impressions")) for n in top_notes_by_impressions],
        },
        "subscriber_growth": subscriber_growth,
        "subscribers_table": [
            {
                "date": (s.get("subscription_created_at") or "")[:10],
                "name": s.get("name") or "",
                "email": s.get("email") or "",
                "type": subscriber_type_label(s),
                "interval": s.get("subscription_interval") or "",
                "activity_rating": safe_num(s.get("activity_rating")),
                "revenue": safe_num(s.get("total_revenue_generated")),
            }
            for s in subscribers
        ],
        "posts_activity_by_month": posts_activity_by_month,
        "notes_activity_by_month": notes_activity_by_month,
        "notes_by_type": notes_by_type,
        "posts_trend": {
            "labels": [r["run_timestamp"] for r in posts_trend],
            "total_views": [safe_num(r["total_views"]) for r in posts_trend],
            "total_opens": [safe_num(r["total_opens"]) for r in posts_trend],
            "avg_open_rate": [round(safe_num(r["avg_open_rate"]) * 100, 1) for r in posts_trend],
        },
        "notes_trend": {
            "labels": [r["run_timestamp"] for r in notes_trend],
            "total_reactions": [safe_num(r["total_reactions"]) for r in notes_trend],
            "total_impressions": [safe_num(r["total_impressions"]) for r in notes_trend],
        },
        "posts_table": [
            {
                "post_id": p.get("post_id"),
                "title": p.get("title") or "",
                "url": f"https://{PUBLICATION}.substack.com/p/{slugify_title(p.get('title'))}",
                "date": (p.get("post_date") or "")[:10],
                "views": safe_num(p.get("views")),
                "opens": safe_num(p.get("opens")),
                "open_rate": round(safe_num(p.get("open_rate")) * 100, 1),
                "your_own_opens": p.get("your_own_opens") if p.get("your_own_opens") is not None else "—",
                "likes": safe_num(p.get("likes")),
                "comments": safe_num(p.get("comments")),
                "restacks": safe_num(p.get("restacks")),
                "tags": p.get("tags") or "",
            }
            for p in posts
        ],
        "notes_table": [
            {
                "note_id": n.get("note_id"),
                "date": (n.get("date") or "")[:10],
                "body": note_label(n.get("body")),
                "type": n.get("note_type") or "Unknown (re-run to categorize)",
                "impressions": n.get("impressions") if n.get("impressions") is not None else "—",
                "reactions": safe_num(n.get("reaction_count")),
                "restacks": safe_num(n.get("restacks")),
                "replies": safe_num(n.get("children_count")),
            }
            for n in notes
        ],
        "post_history": post_history,
        "note_history": note_history,
        "post_traffic_by_id": post_traffic_by_id,
        "overall_traffic_chart": {
            "labels": [c for c, v in overall_traffic_sorted],
            "views": [v for c, v in overall_traffic_sorted],
        },
    }

    html = HTML_TEMPLATE.replace("__DATA_JSON__", json.dumps(data))
    html = html.replace("__PUBLICATION_NAME__", PUBLICATION)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(DASHBOARD_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    # These are real, separate files living next to this script — not
    # embedded as Python string content, specifically so they can be
    # edited and syntax-checked directly as CSS/JS, with no risk of
    # Python's string escaping silently corrupting them. Copy them into
    # the output folder each run so the whole dashboard stays
    # self-contained there (needed for the local server, which serves
    # everything from OUTPUT_DIR).
    for asset in ("Substack App - Dashboard.css", "Substack App - Dashboard.js"):
        src = asset
        dst = os.path.join(OUTPUT_DIR, asset)
        if os.path.exists(src):
            shutil.copyfile(src, dst)
        else:
            print(f"  [!] WARNING: '{src}' not found next to Substack App - Main.py — the")
            print(f"      dashboard will be missing its {'styling' if asset.endswith('.css') else 'functionality'}.")
            print(f"      Make sure it's saved in the same folder as the main script.")

    print(f"Dashboard written to {DASHBOARD_PATH}")
    print(f"  {total_posts} posts, {total_notes} notes, {len(posts_trend)} historical run(s) tracked")

    try:
        webbrowser.open(f"file://{os.path.abspath(DASHBOARD_PATH)}")
        print("Opened dashboard.html in your browser.")
    except Exception as e:
        print(f"  [!] Couldn't auto-open the browser ({e}) — just open {DASHBOARD_PATH} manually.")

    return DASHBOARD_PATH


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>__PUBLICATION_NAME__ — Stats</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<link rel="stylesheet" href="Substack%20App%20-%20Dashboard.css">
</head>
<body>

<header>
  <h1>__PUBLICATION_NAME__</h1>
  <p class="tagline">Substack publication stats, pulled from your own account</p>
  <div class="updated-row">
    <p class="updated" id="updated-at"></p>
    <button class="text-btn" id="refreshBtn" title="Reload this page from disk — useful if you've re-run the pull script in another window and want this tab to catch up">↻ Refresh</button>
  </div>

  <div class="control-panel" id="controlPanel" style="display:none;">
    <div class="control-panel-buttons">
      <button class="cp-btn" data-mode="recent" data-days="7">Refresh: last 7 days</button>
      <button class="cp-btn" data-mode="recent" data-days="14">Refresh: last 14 days</button>
      <button class="cp-btn" data-mode="recent" data-days="30">Refresh: last 30 days</button>
      <button class="cp-btn" data-mode="full">Full historical pull</button>
      <button class="cp-btn" data-mode="dashboard-only">Rebuild dashboard only</button>
    </div>
    <div id="controlPanelStatus" class="control-panel-status"></div>
    <pre id="controlPanelLog" class="control-panel-log" style="display:none;"></pre>
  </div>
  <p class="no-trend" id="controlPanelOffline" style="display:none;">
    Control Panel unavailable — this page was opened directly from disk, not through the
    local server. Start <code>local_server.py</code> (or double-click
    <code>Substack App - Start Server.bat</code>) and open this dashboard at
    <code>http://localhost:8765/dashboard.html</code> instead to enable in-browser controls.
  </p>

  <div class="control-panel">
    <div class="control-panel-buttons">
      <button class="cp-btn" id="strategyBtn">📋 Copy content strategy prompt (last 30 days)</button>
    </div>
    <div id="strategyStatus" class="control-panel-status"></div>
    <p class="no-trend" style="margin-top:8px;">Builds a prompt from your real last-30-days performance —
      top posts, top notes, and note types — and copies it to your clipboard. Paste it into a new Claude
      conversation for content ideas and reflective prompts grounded in what's actually working.</p>
  </div>
</header>

<main>
  <nav class="tab-nav">
    <button class="tab-btn active" data-tab="posts">Posts</button>
    <button class="tab-btn" data-tab="notes">Notes</button>
    <button class="tab-btn" data-tab="comments">Comments</button>
    <button class="tab-btn" data-tab="subscribers">Subscribers</button>
    <button class="tab-btn" data-tab="log">Log</button>
  </nav>

  <div class="tab-panel active" id="tab-posts">
    <div class="kpi-row" id="posts-kpi-row"></div>
    <div class="steady-line"></div>

    <section>
      <h2>Top posts</h2>
      <div class="chart-grid">
        <div class="chart-card"><canvas id="topPostsChart" height="220"></canvas></div>
        <div class="chart-card"><canvas id="topPostsOpensChart" height="220"></canvas></div>
      </div>
    </section>

    <section>
      <h2>Traffic sources</h2>
      <p class="no-trend" style="padding:0 0 12px;">Where views come from, summed across every post —
        Email, Direct, Social, etc. Click any post below for its own breakdown.</p>
      <table id="overallTrafficTable">
        <thead>
          <tr>
            <th>Source</th>
            <th class="num">Views</th>
            <th class="num">% of total</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </section>

    <section>
      <h2>Activity by month</h2>
      <p class="no-trend" style="padding:0 0 12px;">Views and opens grouped by when each post was actually
        published — works from a single pull, no need to wait for repeated runs.</p>
      <div class="chart-grid">
        <div class="chart-card"><canvas id="postsViewsByMonthChart" height="220"></canvas></div>
        <div class="chart-card"><canvas id="postsOpensByMonthChart" height="220"></canvas></div>
      </div>
    </section>

    <section>
      <h2>All posts</h2>
      <p class="no-trend" style="padding:0 0 12px;">Grouped by month — click a month row to collapse or expand it,
        or jump straight to a specific month using the tabs below.</p>
      <div class="month-tabs" id="postsMonthTabs"></div>
      <div class="table-controls">
        <input type="text" id="postsFilter" placeholder="Filter by title or tag…">
        <button class="text-btn" id="postsTableExpandAll">Expand all</button>
        <button class="text-btn" id="postsTableCollapseAll">Collapse all</button>
      </div>
      <table id="postsTable">
        <thead>
          <tr>
            <th data-key="title">Title</th>
            <th data-key="date">Date</th>
            <th data-key="views" class="num">Views</th>
            <th data-key="opens" class="num">Opens</th>
            <th data-key="open_rate" class="num">Open %</th>
            <th data-key="your_own_opens" class="num">Your opens</th>
            <th data-key="likes" class="num">Likes</th>
            <th data-key="comments" class="num">Comments</th>
            <th data-key="restacks" class="num">Restacks</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </section>
  </div>

  <div class="tab-panel" id="tab-notes">
    <div class="kpi-row" id="notes-kpi-row"></div>
    <div class="steady-line"></div>

    <section>
      <h2>Top notes</h2>
      <div class="chart-grid">
        <div class="chart-card"><canvas id="topNotesChart" height="220"></canvas></div>
        <div class="chart-card"><canvas id="topNotesImpressionsChart" height="220"></canvas></div>
      </div>
    </section>

    <section>
      <h2>Activity by month</h2>
      <p class="no-trend" style="padding:0 0 12px;">Reactions and impressions grouped by when each note was actually
        posted — works from a single pull, no need to wait for repeated runs.</p>
      <div class="chart-grid">
        <div class="chart-card"><canvas id="notesReactionsByMonthChart" height="220"></canvas></div>
        <div class="chart-card"><canvas id="notesImpressionsByMonthChart" height="220"></canvas></div>
      </div>
    </section>

    <section>
      <h2>By type</h2>
      <p class="no-trend" style="padding:0 0 12px;">What kind of note you post most, and how each type tends to
        perform — based on real attachment data, not guesswork.</p>
      <div class="chart-grid">
        <div class="chart-card"><canvas id="notesByTypeCountChart" height="220"></canvas></div>
        <div class="chart-card"><canvas id="notesByTypeReactionsChart" height="220"></canvas></div>
      </div>
    </section>

    <section>
      <h2>All notes</h2>
      <p class="no-trend" style="padding:0 0 12px;">Grouped by month — click a month row to collapse or expand it,
        or jump straight to a specific month using the tabs below.</p>
      <div class="month-tabs" id="notesMonthTabs"></div>
      <div class="table-controls">
        <input type="text" id="notesFilter" placeholder="Filter by text…">
        <button class="text-btn" id="notesTableExpandAll">Expand all</button>
        <button class="text-btn" id="notesTableCollapseAll">Collapse all</button>
      </div>
      <table id="notesTable">
        <thead>
          <tr>
            <th data-key="date">Date</th>
            <th data-key="body">Note</th>
            <th data-key="type">Type</th>
            <th data-key="impressions" class="num">Impressions</th>
            <th data-key="reactions" class="num">Reactions</th>
            <th data-key="restacks" class="num">Restacks</th>
            <th data-key="replies" class="num">Replies</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </section>
  </div>

  <div class="tab-panel" id="tab-subscribers">
    <div class="kpi-row" id="subscribers-kpi-row"></div>
    <div class="steady-line"></div>

    <section>
      <h2>Growth</h2>
      <p class="no-trend" style="padding:0 0 12px;">Reconstructed from individual signup dates in your subscriber
        list — this works from a single pull, no need to wait for repeated runs.</p>
      <div class="chart-grid">
        <div class="chart-card"><canvas id="subscriberCumulativeChart" height="220"></canvas></div>
        <div class="chart-card"><canvas id="subscriberNewChart" height="220"></canvas></div>
      </div>
    </section>

    <section>
      <h2>All subscribers</h2>
      <p class="no-trend" style="padding:0 0 12px;">Grouped by month — click a month row to collapse or expand it,
        or jump straight to a specific month using the tabs below. Names and emails are your subscriber CRM
        data, same as Substack's own dashboard shows you — keep in mind this file lives in a synced folder.</p>
      <div class="month-tabs" id="subscribersMonthTabs"></div>
      <div class="table-controls">
        <input type="text" id="subscribersFilter" placeholder="Filter by name, email, or type…">
        <button class="text-btn" id="subscribersTableExpandAll">Expand all</button>
        <button class="text-btn" id="subscribersTableCollapseAll">Collapse all</button>
      </div>
      <table id="subscribersTable">
        <thead>
          <tr>
            <th data-key="date">Signup date</th>
            <th data-key="name">Name</th>
            <th data-key="email">Email</th>
            <th data-key="type">Type</th>
            <th data-key="interval">Interval</th>
            <th data-key="activity_rating" class="num">Activity</th>
            <th data-key="revenue" class="num">Revenue</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </section>
  </div>

  <div class="tab-panel" id="tab-log">
    <div class="kpi-row" id="log-kpi-row"></div>
    <div class="steady-line"></div>

    <section>
      <h2>Pull log</h2>
      <p class="no-trend" style="padding:0 0 12px;">Every time you've run the pull script, and how much was
        captured each time — grouped by month, or jump to a specific month using the tabs below.</p>
      <div class="month-tabs" id="logMonthTabs"></div>
      <div class="table-controls">
        <input type="text" id="logFilter" placeholder="Filter by date…">
        <button class="text-btn" id="logTableExpandAll">Expand all</button>
        <button class="text-btn" id="logTableCollapseAll">Collapse all</button>
      </div>
      <table id="logTable">
        <thead>
          <tr>
            <th data-key="timestamp">Timestamp</th>
            <th data-key="posts" class="num">Posts</th>
            <th data-key="notes" class="num">Notes</th>
            <th data-key="subscribers" class="num">Subscribers</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </section>
  </div>

  <div class="tab-panel" id="tab-comments">
    <div class="kpi-row" id="comments-kpi-row"></div>
    <div class="steady-line"></div>

    <section>
      <h2>Reader comments</h2>
      <p class="no-trend" style="padding:0 0 12px;">Comments readers left on your posts — a source of ideas for
        future posts and notes. Click the link icon to go read a comment in context.
        <strong>This feature hasn't been verified against your live account yet</strong> — built from public
        documentation only. If this table is empty after a real pull, that's expected until confirmed;
        check the terminal output from the "PULLING COMMENTS" step for details.</p>
      <div class="month-tabs" id="commentsMonthTabs"></div>
      <div class="table-controls">
        <input type="text" id="commentsFilter" placeholder="Filter by post, commenter, or text…">
        <button class="text-btn" id="commentsTableExpandAll">Expand all</button>
        <button class="text-btn" id="commentsTableCollapseAll">Collapse all</button>
      </div>
      <table id="commentsTable">
        <thead>
          <tr>
            <th data-key="post_title">Post</th>
            <th data-key="date">Date</th>
            <th data-key="commenter_name">Commenter</th>
            <th data-key="body">Comment</th>
            <th data-key="reactions" class="num">Reactions</th>
            <th data-key="replies" class="num">Replies</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </section>
  </div>
</main>

<div class="modal-overlay" id="detailModal">
  <div class="modal-content">
    <button class="modal-close" id="modalClose">&times;</button>
    <h3 id="modalTitle"></h3>
    <p class="no-trend" id="modalSubtitle"></p>
    <canvas id="modalChart" height="280"></canvas>
    <div id="modalTrafficSection" style="display:none; margin-top:20px;">
      <h4 style="font-family:'Fraunces',serif; font-size:15px; margin:0 0 10px;">Traffic sources</h4>
      <table id="modalTrafficTable">
        <thead>
          <tr>
            <th>Source</th>
            <th class="num">Views</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
</div>

<script>
const DATA = __DATA_JSON__;
</script>
<script src="Substack%20App%20-%20Dashboard.js"></script>

</body>
</html>
"""



# ==================== MAIN ====================
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    dashboard_only = "--dashboard-only" in sys.argv or "-d" in sys.argv

    if dashboard_only:
        print("=" * 50)
        print("REBUILDING DASHBOARD ONLY (no new data pulled)")
        print("=" * 50)
        build_dashboard()
        print()
        print("=" * 50)
        print("ALL DONE")
        print("=" * 50)
        return

    # --recent N (or -r N): only refresh posts/notes/comments from the
    # last N days, instead of grinding through full history every time.
    # Older items simply aren't touched this run — their last known
    # values from an earlier full pull stay exactly as they were.
    recent_days = None
    for i, arg in enumerate(sys.argv):
        if arg in ("--recent", "-r") and i + 1 < len(sys.argv):
            try:
                recent_days = int(sys.argv[i + 1])
            except ValueError:
                print(f"ERROR: --recent needs a number of days, got '{sys.argv[i + 1]}'")
                sys.exit(1)

    cutoff_date = None
    if recent_days is not None:
        from datetime import timedelta
        cutoff_date = (datetime.now() - timedelta(days=recent_days)).strftime("%Y-%m-%d")

    if not COOKIE:
        print_no_cookie_error()
        sys.exit(1)

    if cutoff_date:
        print("=" * 50)
        print(f"RECENT-WINDOW PULL — last {recent_days} days (since {cutoff_date})")
        print("=" * 50)
        print("Older posts/notes/comments won't be touched this run — their existing")
        print("data stays exactly as it was from your last full pull.")
        print()

    print("=" * 50)
    print("PULLING POSTS")
    print("=" * 50)
    posts = fetch_post_stats()
    if not posts:
        print("No posts retrieved — stopping. Check TROUBLESHOOTING.md.")
        return

    if cutoff_date:
        before = len(posts)
        posts = [p for p in posts if (p.get("post_date") or "9999")[:10] >= cutoff_date]
        print(f"  -> {len(posts)}/{before} posts fall within the last {recent_days} days")
        if not posts:
            print("  No posts in this window — skipping the rest of the posts step.")

    if posts and FETCH_OWN_OPENS:
        print(f"\nLooking up your own opens for {len(posts)} posts...")
        for i, p in enumerate(posts, 1):
            p["your_own_opens"] = fetch_own_opens(p.get("post_id"))
            if i % 10 == 0 or i == len(posts):
                print(f"  ...{i}/{len(posts)} posts checked")
            time.sleep(OWN_OPENS_DELAY_SECONDS)
        found = sum(1 for p in posts if p.get("your_own_opens") is not None)
        print(f"  -> found your own opens on {found}/{len(posts)} posts")

    post_traffic = {}
    if posts and FETCH_TRAFFIC:
        print(f"\nLooking up traffic sources for {len(posts)} posts...")
        for i, p in enumerate(posts, 1):
            post_id = p.get("post_id")
            categories = fetch_post_traffic(post_id)
            if categories:
                post_traffic[post_id] = categories
            if i % 10 == 0 or i == len(posts):
                print(f"  ...{i}/{len(posts)} posts checked")
            time.sleep(TRAFFIC_DELAY_SECONDS)
        print(f"  -> found traffic data on {len(post_traffic)}/{len(posts)} posts")

    if posts:
        conn = sqlite3.connect(DB_PATH)
        init_posts_db(conn)
        n = save_post_snapshot(conn, posts, run_timestamp)
        print(f"Saved {n} post snapshots to {DB_PATH}")
        export_latest_posts_csv(conn, os.path.join(OUTPUT_DIR, "latest_snapshot.csv"))
        export_full_posts_history_csv(conn, os.path.join(OUTPUT_DIR, "full_history.csv"))
        if post_traffic:
            init_traffic_db(conn)
            for post_id, categories in post_traffic.items():
                save_traffic_snapshot(conn, post_id, categories, run_timestamp)
            print(f"Saved traffic snapshots for {len(post_traffic)} posts")
        conn.close()
        print("Wrote latest_snapshot.csv and full_history.csv")

    print()
    print("=" * 50)
    print("PULLING NOTES")
    print("=" * 50)
    notes = fetch_notes(stop_at_date=cutoff_date)
    if not notes:
        print("No notes retrieved — skipping notes, will still build dashboard from posts.")
    else:
        if FETCH_IMPRESSIONS:
            print(f"\nLooking up impressions for {len(notes)} notes...")
            for i, n in enumerate(notes, 1):
                n["impressions"] = fetch_note_impressions(n.get("id"))
                if i % 10 == 0 or i == len(notes):
                    print(f"  ...{i}/{len(notes)} notes checked")
                time.sleep(IMPRESSIONS_DELAY_SECONDS)
            found = sum(1 for n in notes if n.get("impressions") is not None)
            print(f"  -> found impressions on {found}/{len(notes)} notes")

        conn = sqlite3.connect(DB_PATH)
        init_notes_db(conn)
        n = save_note_snapshot(conn, notes, run_timestamp)
        print(f"Saved {n} note snapshots to {DB_PATH}")
        export_latest_notes_csv(conn, os.path.join(OUTPUT_DIR, "latest_notes_snapshot.csv"))
        export_full_notes_history_csv(conn, os.path.join(OUTPUT_DIR, "full_notes_history.csv"))
        conn.close()
        print("Wrote latest_notes_snapshot.csv and full_notes_history.csv")

    print()
    print("=" * 50)
    print("PULLING COMMENTS")
    print("=" * 50)
    if FETCH_COMMENTS and not posts:
        print("No posts in this window — skipping comments.")
    elif FETCH_COMMENTS:
        print(f"Looking up comments for {len(posts)} posts (one request per post — this endpoint")
        print("is UNVERIFIED against this account, built from public documentation only; if it")
        print("errors or returns nothing, that's expected until confirmed for real)...")
        all_comments = []
        errors = 0
        for i, p in enumerate(posts, 1):
            post_url = f"https://{PUBLICATION}.substack.com/p/{slugify_title(p.get('title'))}"
            try:
                post_comments = fetch_post_comments(p.get("post_id"), post_url)
                for c in post_comments:
                    c["post_title"] = p.get("title")
                all_comments.extend(post_comments)
            except Exception as e:
                errors += 1
            if i % 10 == 0 or i == len(posts):
                print(f"  ...{i}/{len(posts)} posts checked, {len(all_comments)} comments found so far")
            time.sleep(COMMENTS_DELAY_SECONDS)

        if errors == len(posts):
            print(f"  [!] All {errors} requests failed — the endpoint likely needs verifying.")
            print("      See the docstring on fetch_post_comments() for what to check.")
        elif not all_comments:
            print("  -> 0 comments found. Either no comments exist yet, or the response shape")
            print("     needs verifying — see fetch_post_comments() docstring.")
        else:
            print(f"  -> {len(all_comments)} comments found across {len(posts)} posts")
            conn = sqlite3.connect(DB_PATH)
            init_comments_db(conn)
            n = save_comment_snapshot(conn, all_comments, run_timestamp)
            print(f"Saved {n} comment snapshots to {DB_PATH}")
            export_latest_comments_csv(conn, os.path.join(OUTPUT_DIR, "latest_comments_snapshot.csv"))
            conn.close()
            print("Wrote latest_comments_snapshot.csv")
    else:
        print("FETCH_COMMENTS is False — skipping.")

    print()
    print("=" * 50)
    print("PULLING SUBSCRIBERS")
    print("=" * 50)
    if FETCH_SUBSCRIBERS:
        subs = fetch_subscribers()
        if not subs:
            print("No subscribers retrieved — skipping, will still build dashboard from posts/notes.")
        else:
            conn = sqlite3.connect(DB_PATH)
            init_subscribers_db(conn)
            n = save_subscriber_snapshot(conn, subs, run_timestamp)
            print(f"Saved {n} subscriber snapshots to {DB_PATH}")
            export_latest_subscribers_csv(conn, os.path.join(OUTPUT_DIR, "latest_subscribers_snapshot.csv"))
            conn.close()
            print("Wrote latest_subscribers_snapshot.csv")
    else:
        print("FETCH_SUBSCRIBERS is False — skipping.")

    print()
    print("=" * 50)
    print("BUILDING DASHBOARD")
    print("=" * 50)
    build_dashboard()

    print()
    print("=" * 50)
    print("ALL DONE")
    print("=" * 50)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nStopped — no partial data was saved from this run (database writes only")
        print("commit once a full step finishes, so interrupting mid-run doesn't leave")
        print("anything half-written). Your history from previous runs is untouched.")
        print("Run the script again whenever you're ready for a fresh, complete pull.")
        sys.exit(1)
