// Reads cookies for whichever Substack page you currently have open in
// this tab — works for any publication, not just one hardcoded one. A
// request to that page's URL pulls in both that publication's cookies
// AND the broader .substack.com session cookie (like substack.sid),
// since Substack's session cookie is scoped to the whole domain.

const btn = document.getElementById("copyBtn");
const statusEl = document.getElementById("status");

function setStatus(message, type) {
  statusEl.textContent = message;
  statusEl.className = type || "";
}

async function getActiveSubstackTabUrl() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url) {
    throw new Error("Couldn't read the current tab.");
  }
  let hostname;
  try {
    hostname = new URL(tab.url).hostname;
  } catch (e) {
    throw new Error("This doesn't look like a valid page.");
  }
  if (hostname !== "substack.com" && !hostname.endsWith(".substack.com")) {
    throw new Error(
      "This isn't a Substack page. Go to your own Substack (e.g. " +
      "yourpublication.substack.com), logged in, then click this again."
    );
  }
  return tab.url;
}

btn.addEventListener("click", async () => {
  btn.disabled = true;
  setStatus("Reading cookies…", "");

  try {
    const targetUrl = await getActiveSubstackTabUrl();
    const cookies = await chrome.cookies.getAll({ url: targetUrl });

    if (!cookies || cookies.length === 0) {
      setStatus(
        "No cookies found for this page. Make sure you're logged into " +
        "Substack in this browser.",
        "error"
      );
      btn.disabled = false;
      return;
    }

    const cookieString = cookies.map(c => `${c.name}=${c.value}`).join("; ");

    await navigator.clipboard.writeText(cookieString);

    setStatus(
      `Copied ${cookies.length} cookie(s) to clipboard (${cookieString.length} characters). ` +
      `Paste this into your cookie file now.`,
      "success"
    );
  } catch (err) {
    setStatus(`Error: ${err.message || err}`, "error");
  } finally {
    btn.disabled = false;
  }
});
