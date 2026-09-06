# Substack App — Setup & Usage Guide

A free, self-hosted dashboard for your own Substack stats — posts, Notes,
subscribers, comments, and traffic sources, tracked over time on your own
computer. No subscription, no third-party service, no data ever leaves
your machine.

This guide assumes no technical background. Every step is spelled out.
Total setup time: about 10 minutes, once.

---

## How this works, in one paragraph

Substack doesn't offer an official way to export all of this data. This
app works by using your own logged-in browser session to ask Substack for
the same information your own Substack dashboard already shows you — just
gathered into one place and saved over time, so you can see trends instead
of just a snapshot. Nothing here is official or guaranteed by Substack, but
it's built to fail safely: if something ever breaks, it tells you clearly
rather than showing you wrong numbers.

---

## What you'll need

- **A Windows or Mac computer** (this guide uses Windows screenshots'
  worth of description; Mac steps are the same with different menus)
- **Google Chrome**, logged into your Substack
- **Python**, a free program — if you don't have it, Step 1 covers
  installing it (takes 3 minutes)
- 10 minutes

---

## Step 1 — Install Python (skip if you already have it)

1. Go to **[python.org/downloads](https://python.org/downloads)**
2. Click the big yellow "Download Python" button
3. Run the installer
4. **Important:** on the first install screen, check the box that says
   **"Add python.exe to PATH"** (or "Add Python to PATH") before clicking
   Install. This is the single most common setup mistake — if you skip
   it, nothing else in this guide will work until you reinstall with that
   box checked.

To check whether Python is already installed: open Command Prompt
(search "cmd" in your Start menu) and type:
```
python --version
```
If you see something like `Python 3.12.1`, you're already set — skip to
Step 2.

---

## Step 2 — Put the app files in a folder

1. Create a new folder anywhere you like — for example, on your Desktop,
   named `Substack App`
2. Move every file from this download into that folder, including the
   `Substack App - Cookie Extension` folder and the empty
   `.substack_cookie.txt` file — everything should be directly inside
   your one folder, nothing nested any deeper than that
   - **Windows:** `.substack_cookie.txt` may be hidden. In File Explorer
     click **View → Show → Hidden items** so you can see it

---

## Step 3 — Install the Chrome extension (grabs your login session)

This extension is what lets the app act as "you" when asking Substack for
your stats — the same way your browser already proves who you are every
time you visit your own dashboard. It never sends anything anywhere except
your own clipboard.

1. Open Chrome and go to `chrome://extensions` in the address bar
2. Turn on **Developer mode** — a toggle switch in the top-right corner
3. Click **Load unpacked**
4. Select the `Substack App - Cookie Extension` folder (the whole folder,
   not a file inside it)
5. You should now see "Substack App Cookie Copier" in your extensions list
6. Click the puzzle-piece icon in Chrome's toolbar (near the address bar)
   and pin this extension so it's always one click away
7. If you already had the extension installed from an earlier copy of
   this app, go back to `chrome://extensions` and click **Reload** on
   its card so it picks up the new session fields

---

## Step 4 — Get your cookie, subdomain, and user ID

1. Go to your own Substack (e.g. `yourpublication.substack.com`), logged
   in as yourself, in Chrome
2. Click the Substack App Cookie Copier icon you just pinned
3. Click **"Copy session to clipboard"**
4. You'll see your subdomain, numeric user ID, and a cookie count — that
   means it worked and all three are now copied together

Now paste it into the file that already comes with the app — don't
create a new one:

5. In your `Substack App` folder, open `.substack_cookie.txt`
   - **Windows:** if you don't see it, click **View → Show → Hidden
     items**, then right-click the file → Open with → Notepad
   - **Mac:** open it with TextEdit (plain text) or any text editor
6. Paste (Ctrl+V / Cmd+V). The text will look like JSON (publication,
   user ID, and cookie together) — that's expected
7. Save and close the file

**This file is a live login credential** — anyone who has it can act as
you on Substack until it expires (typically days to weeks). Don't email
it, share it, or upload it anywhere.

**This step will need repeating every few weeks**, whenever your cookie
expires — same two clicks (extension → copy → paste over the old
contents of `.substack_cookie.txt`).

---

## Step 5 — Run it for the first time

1. Inside your `Substack App` folder, double-click **`Substack App - Run
   Dashboard.bat`**
2. A black window (Command Prompt) will open. The first time, the app
   reads your cookie file and looks up your subdomain and numeric user
   ID from your Substack session — you should not have to type them.

   If that lookup fails (usually an expired or missing cookie), it will
   ask two quick questions instead:

   **"Your subdomain:"** — type the part of your Substack address before
   `.substack.com`. If your Substack is at `example.substack.com`, type
   `example`

   **"Your numeric user ID:"** — a number, not your name. The fastest
   fix is to redo Step 4 with the updated extension. Or look it up:
   - Go to `substack.com/notes`, logged in
   - Press **F12** to open DevTools
   - Click the **Network** tab near the top of the DevTools panel
   - Click the **Fetch/XHR** filter button
   - Refresh the page (F5)
   - Look through the list on the left for something starting with
     `profile/` followed by a number — for example `profile/123456789`
   - That number is your user ID — type it in and press Enter

3. That's it for setup — it's saved and won't ask again. The app will now
   start pulling your real data (this first pull can take a few minutes,
   since it goes through your full history) and open your dashboard in
   Chrome automatically when done.

If it prints an error about a missing cookie, that just means Step 4
didn't quite land — open `.substack_cookie.txt` in this same folder,
paste again, save, then double-click the same `.bat` file again.

---

## Day-to-day use

You don't need to redo any of the above again. From here on:

| To do this... | Double-click this file |
|---|---|
| Full refresh (all your history) | `Substack App - Run Dashboard.bat` |
| Quick refresh, last 7 days only | `Substack App - Refresh Last 7 Days.bat` |
| Quick refresh, last 14 days | `Substack App - Refresh Last 14 Days.bat` |
| Quick refresh, last 30 days | `Substack App - Refresh Last 30 Days.bat` |
| Just reopen the dashboard, no new data | run the full refresh, then use the **↻ Refresh** button inside the dashboard itself |

The "last N days" options are much faster than a full refresh, and are
what you'll want most days — a full refresh is worth doing every week or
two to make sure nothing drifts.

### Optional: control everything from your browser instead

If you'd rather click buttons in the dashboard itself instead of
double-clicking files:

1. Double-click **`Substack App - Start Server.bat`** once — leave that
   black window open in the background
2. Your browser opens automatically to `http://localhost:8765/dashboard.html`
   — **bookmark this address**
3. A Control Panel now appears at the top of the dashboard with buttons
   for every refresh option above, plus a live progress log right in the
   page

You'll need to double-click "Start Server" again each time you restart
your computer or close that window — everything else after that happens
in the browser.

---

## What's in the dashboard

- **Posts** — views, opens, likes, restacks, and traffic sources (where
  your readers actually come from — email, direct links, social, etc.)
  for every published post
- **Notes** — reactions, restacks, replies, and impressions for every
  Note you've posted, broken down by type (plain text, sharing a post,
  images, links)
- **Comments** — reader comments left on your posts, with a link back to
  read each one in context
- **Subscribers** — growth over time, broken down by free/paid/founding
- **Log** — a record of every time you've pulled data, so you always know
  when your numbers were last updated

Every table can be searched, sorted by clicking any column header, and
filtered by year and month. Click any post or note row to see its
individual history over time.

### The content strategy button

At the top of the dashboard, there's a **"📋 Copy content strategy
prompt"** button. Click it, and it copies a prompt to your clipboard built
from your real last-30-days performance — your top posts, top notes, and
what's actually resonating. Paste it into a conversation with Claude (or
any AI assistant) for content ideas grounded in your real numbers, not
generic advice.

---

## Troubleshooting

**"Could not find 'python' or 'py' on your PATH"**
Python isn't installed, or was installed without the "Add to PATH" box
checked. Reinstall from python.org and make sure that box is checked.

**"ERROR: No Substack cookie found"**
Redo Step 4 — open the `.substack_cookie.txt` file that came with the
app, paste the extension copy, and save. Don't create a second file.

**A pull runs but every number comes back as zero / empty**
Almost always an expired cookie. Redo Step 4 (click the extension, copy,
paste over the old file) and try again.

**The dashboard opens but looks broken / unstyled**
Make sure every file from the download — including `Substack App -
Dashboard.css` and `Substack App - Dashboard.js` — is in the same folder
as `Substack App - Main.py`, not moved or renamed.

**Something else looks wrong**
The terminal window that opens when you run the app prints exactly what
it's doing at each step — if a specific piece of data (like Comments,
or Traffic Sources) isn't showing up, the terminal will usually say so
directly rather than failing silently. That message is the best starting
point for figuring out what happened.

---

## Privacy notes

- Your cookie stays in `.substack_cookie.txt` in this folder, and your
  pulled data stays in the `output` folder — nothing is sent to any
  third party. Don't share that cookie file.
- The Chrome extension only ever reads cookies, subdomain, and user ID
  for Substack pages you have open yourself, and only copies to your
  own clipboard when you click the button — it doesn't run in the
  background or send anything anywhere
- If you ever want to fully remove this app, delete the folder — there's
  nothing installed elsewhere on your system except the Chrome extension,
  which you can remove from `chrome://extensions`
