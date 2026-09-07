const assert = require("assert");

// popup.js attaches a click handler at load time; stub the DOM first.
const preview = { hidden: true };
document = {
  getElementById: (id) => {
    if (id === "copyBtn") return { addEventListener() {} };
    if (id === "status") return { textContent: "", className: "" };
    if (id === "preview") return preview;
    return { textContent: "" };
  },
};

const {
  subdomainFromHostname,
  normalizePublication,
  asUserId,
  pickPublication,
  isUserCancel,
} = require("../popup.js");

assert.strictEqual(subdomainFromHostname("demo.substack.com"), "demo");
assert.strictEqual(subdomainFromHostname("open.substack.com"), null);
assert.strictEqual(subdomainFromHostname("substack.com"), null);
assert.strictEqual(subdomainFromHostname("www.substack.com"), null);

assert.strictEqual(normalizePublication("https://Demo.substack.com/p/hi"), "demo");
assert.strictEqual(normalizePublication("open.substack.com"), null);
assert.strictEqual(asUserId(123456), "123456");
assert.strictEqual(asUserId("12a"), null);

assert.strictEqual(
  pickPublication("demo", {
    subdomain: "other",
    publications: [{ subdomain: "demo", isPrimary: false, role: "admin" }],
  }),
  "demo"
);
assert.strictEqual(
  pickPublication(null, {
    subdomain: null,
    publications: [
      { subdomain: "second", isPrimary: false, role: "writer" },
      { subdomain: "primary", isPrimary: true, role: "admin" },
    ],
  }),
  "primary"
);
assert.strictEqual(
  pickPublication(null, {
    subdomain: "from-preloads",
    publications: [],
  }),
  "from-preloads"
);

assert.strictEqual(isUserCancel(new Error("Download canceled by the user.")), true);
assert.strictEqual(isUserCancel(new Error("USER_CANCELED")), true);
assert.strictEqual(isUserCancel(new Error("network failed")), false);

console.log("test_popup_helpers.js: ok");
