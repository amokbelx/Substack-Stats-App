// Collects everything the local Substack App needs from whichever
// Substack page you currently have open: the session cookie, the
// publication subdomain, and your numeric user ID. A request to that
// page's URL pulls in both that publication's cookies AND the broader
// .substack.com session cookie (like substack.sid), since Substack's
// session cookie is scoped to the whole domain.

const RESERVED_SUBDOMAINS = new Set(["www", "open", "on", "support"]);

const btn = document.getElementById("copyBtn");
const statusEl = document.getElementById("status");
const previewEl = document.getElementById("preview");
const pubValueEl = document.getElementById("pubValue");
const uidValueEl = document.getElementById("uidValue");
const cookieValueEl = document.getElementById("cookieValue");

function setStatus(message, type) {
  statusEl.textContent = message;
  statusEl.className = type || "";
}

function showPreview(publication, userId, cookieCount) {
  pubValueEl.textContent = publication ? `${publication}.substack.com` : "not found — open your publication";
  uidValueEl.textContent = userId || "not found — make sure you're logged in";
  cookieValueEl.textContent = cookieCount ? `${cookieCount} cookie(s)` : "none";
  previewEl.hidden = false;
}

function subdomainFromHostname(hostname) {
  if (!hostname) return null;
  const host = hostname.toLowerCase();
  if (host === "substack.com") return null;
  if (!host.endsWith(".substack.com")) return null;
  const sub = host.slice(0, -".substack.com".length);
  if (!sub || RESERVED_SUBDOMAINS.has(sub)) return null;
  return sub;
}

function normalizePublication(value) {
  if (value == null) return null;
  let raw = String(value).trim().toLowerCase();
  raw = raw.replace(/^https?:\/\//, "");
  raw = raw.split(".substack.com")[0].split("/")[0].split(":")[0].trim();
  if (!raw || raw === "substack.com" || RESERVED_SUBDOMAINS.has(raw)) return null;
  return raw;
}

function asUserId(value) {
  if (value == null) return null;
  const text = String(value).trim();
  return /^\d+$/.test(text) ? text : null;
}

function pickPublication(tabSubdomain, identity) {
  const pubs = identity.publications || [];
  const pubSubs = pubs.map(p => p.subdomain).filter(Boolean);

  if (tabSubdomain && (pubSubs.length === 0 || pubSubs.includes(tabSubdomain))) {
    return tabSubdomain;
  }
  if (identity.subdomain) return identity.subdomain;
  const primary = pubs.find(p => p.isPrimary && p.subdomain);
  if (primary) return primary.subdomain;
  const admin = pubs.find(p => (p.role === "admin" || p.role === "editor") && p.subdomain);
  if (admin) return admin.subdomain;
  return pubs[0]?.subdomain || tabSubdomain || null;
}

async function getActiveSubstackTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url) {
    throw new Error("Couldn't read the current tab.");
  }
  let parsed;
  try {
    parsed = new URL(tab.url);
  } catch (e) {
    throw new Error("This doesn't look like a valid page.");
  }
  const hostname = parsed.hostname.toLowerCase();
  if (hostname !== "substack.com" && !hostname.endsWith(".substack.com")) {
    throw new Error(
      "This isn't a Substack page. Go to your own Substack (e.g. " +
      "yourpublication.substack.com), logged in, then click this again."
    );
  }
  return { tab, url: tab.url, hostname };
}

// Runs inside the open Substack tab so we can read the page's own
// preloaded data and call Substack as the logged-in user.
async function extractIdentityFromPage() {
  function asId(value) {
    if (value == null) return null;
    const text = String(value).trim();
    return /^\d+$/.test(text) ? text : null;
  }

  function asSubdomain(value) {
    if (value == null) return null;
    let raw = String(value).trim().toLowerCase();
    raw = raw.replace(/^https?:\/\//, "");
    raw = raw.split(".substack.com")[0].split("/")[0].split(":")[0].trim();
    const reserved = ["www", "open", "on", "support", "substack.com", ""];
    if (reserved.includes(raw)) return null;
    return raw;
  }

  const identity = { userId: null, subdomain: null, publications: [] };

  const preloads = window._preloads;
  if (preloads && typeof preloads === "object") {
    const user = preloads.user || preloads.loggedInUser || {};
    identity.userId = asId(user.id || user.user_id);
    const pub = preloads.pub || preloads.publication || {};
    identity.subdomain = asSubdomain(pub.subdomain);
  }

  try {
    const res = await fetch("https://substack.com/api/v1/user/profile/self", {
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    if (res.ok) {
      const data = await res.json();
      identity.userId = asId(data && data.id) || identity.userId;
      const rows = Array.isArray(data && data.publicationUsers) ? data.publicationUsers : [];
      identity.publications = rows
        .map((row) => ({
          subdomain: asSubdomain(row && row.publication && row.publication.subdomain),
          name: (row && row.publication && row.publication.name) || "",
          role: (row && row.role) || "",
          isPrimary: Boolean(row && row.is_primary),
        }))
        .filter((row) => row.subdomain);
    }
  } catch (e) {
    // Fall back to whatever preloads already gave us.
  }

  return identity;
}

async function readIdentity(tabId) {
  try {
    const [injected] = await chrome.scripting.executeScript({
      target: { tabId },
      func: extractIdentityFromPage,
      world: "MAIN",
    });
    if (injected && injected.result) return injected.result;
  } catch (e) {
    // Tab may not allow scripting, or Substack blocked the page script.
  }

  try {
    const res = await fetch("https://substack.com/api/v1/user/profile/self", {
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) return { userId: null, subdomain: null, publications: [] };
    const data = await res.json();
    const publications = (Array.isArray(data.publicationUsers) ? data.publicationUsers : [])
      .map((row) => ({
        subdomain: normalizePublication(row && row.publication && row.publication.subdomain),
        name: (row && row.publication && row.publication.name) || "",
        role: (row && row.role) || "",
        isPrimary: Boolean(row && row.is_primary),
      }))
      .filter((row) => row.subdomain);
    return {
      userId: asUserId(data.id),
      subdomain: null,
      publications,
    };
  } catch (e) {
    return { userId: null, subdomain: null, publications: [] };
  }
}

function isUserCancel(err) {
  const message = String(err && err.message ? err.message : err).toLowerCase();
  return message.includes("cancel") || message.includes("canceled") || message.includes("cancelled");
}

function downloadNamedFile(dataUrl, filename) {
  return new Promise((resolve, reject) => {
    chrome.downloads.download(
      {
        url: dataUrl,
        filename,
        saveAs: true,
        conflictAction: "overwrite",
      },
      (id) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }
        resolve(id);
      }
    );
  });
}

// Chrome cannot write directly into the app folder. Opening a Save
// dialog with the filename already filled in is the closest thing —
// the user only has to pick the Substack App folder. A data: URL is
// used so the download still finishes if this popup closes.
async function saveSessionFile(contents) {
  const dataUrl = "data:text/plain;charset=utf-8," + encodeURIComponent(contents);
  const names = [".substack_cookie.txt", "substack_cookie.txt"];
  let lastError = null;
  for (const filename of names) {
    try {
      await downloadNamedFile(dataUrl, filename);
      return filename;
    } catch (err) {
      lastError = err;
      if (isUserCancel(err)) throw err;
    }
  }
  throw lastError || new Error("Could not open the save dialog.");
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    subdomainFromHostname,
    normalizePublication,
    asUserId,
    pickPublication,
    isUserCancel,
  };
}

btn.addEventListener("click", async () => {
  btn.disabled = true;
  setStatus("Reading session…", "");

  try {
    const { tab, url, hostname } = await getActiveSubstackTab();
    const cookies = await chrome.cookies.getAll({ url });

    if (!cookies || cookies.length === 0) {
      showPreview(subdomainFromHostname(hostname), null, 0);
      setStatus(
        "No cookies found for this page. Make sure you're logged into " +
        "Substack in this browser.",
        "error"
      );
      btn.disabled = false;
      return;
    }

    const cookieString = cookies.map(c => `${c.name}=${c.value}`).join("; ");
    const identity = await readIdentity(tab.id);
    const publication = pickPublication(subdomainFromHostname(hostname), identity);
    const userId = asUserId(identity.userId);

    const bundle = {
      publication,
      user_id: userId,
      cookie: cookieString,
    };

    const contents = JSON.stringify(bundle, null, 2);
    showPreview(publication, userId, cookies.length);
    setStatus("Save this file in your Substack App folder…", "");
    await saveSessionFile(contents);

    if (!publication || !userId) {
      const missing = [
        !publication ? "subdomain" : null,
        !userId ? "user ID" : null,
      ].filter(Boolean).join(" and ");
      setStatus(
        `Saved cookies, but could not find your ${missing}. ` +
        `Open your own publication while logged in (not just substack.com) and try again.`,
        "error"
      );
    } else {
      setStatus(
        `Saved subdomain, user ID, and ${cookies.length} cookie(s). ` +
        `Make sure that file is in your Substack App folder.`,
        "success"
      );
    }
  } catch (err) {
    if (isUserCancel(err)) {
      setStatus("Save cancelled.", "");
    } else {
      setStatus(`Error: ${err.message || err}`, "error");
    }
  } finally {
    btn.disabled = false;
  }
});
