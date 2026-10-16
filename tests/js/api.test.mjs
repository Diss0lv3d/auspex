// The one API client (F4), under Node with a scripted fetch. Every page
// request goes through it, so the bearer header is written in one place, and
// a refusal is handed to the shell rather than judged here (D-070).
//
//   node --test tests/js/api.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { createApi } from "../../auspex/static/js/api.js";
import { NETWORK } from "../../auspex/static/js/shell-logic.js";

// Answers from a script, the way the browser's fetch would: a Response-like
// object with ok, status, json() and a body. An Error in the script rejects.
function fakeFetch(answers) {
  const calls = [];
  const fetch = async (path, init) => {
    calls.push({ path, init });
    const a = answers.shift();
    if (a instanceof Error) throw a;
    return {
      ok: a.status >= 200 && a.status < 300, status: a.status, body: "the stream",
      json: async () => { if (a.body === undefined) throw new SyntaxError("not JSON"); return a.body; },
    };
  };
  return { fetch, calls };
}
const counting = () => {
  const seen = { forbidden: 0, expired: 0 };
  return { seen, onForbidden: () => { seen.forbidden++; }, onExpired: () => { seen.expired++; } };
};

test("every request carries the tab's token as a bearer header", async () => {
  const { fetch, calls } = fakeFetch([{ status: 200, body: {} }, { status: 200, body: {} }]);
  const api = createApi({ fetch, token: () => "tok" });
  await api.get("/api/x");
  await api.post("/api/y", { a: 1 });
  assert.equal(calls[0].init.method, "GET");
  assert.equal(calls[0].init.headers.Authorization, "Bearer tok");
  assert.equal(calls[1].init.method, "POST");
  assert.equal(calls[1].init.headers.Authorization, "Bearer tok");
  assert.equal(calls[1].init.headers["Content-Type"], "application/json");
  assert.equal(calls[1].init.body, JSON.stringify({ a: 1 }));
});

test("a POST without a body sends neither a body nor a content type", async () => {
  const { fetch, calls } = fakeFetch([{ status: 200, body: {} }]);
  await createApi({ fetch, token: () => "t" }).post("/api/proposals/x/reject");
  assert.equal(calls[0].init.body, undefined);
  assert.equal("Content-Type" in calls[0].init.headers, false);
});

test("signed out, no Authorization header is sent at all", async () => {
  const { fetch, calls } = fakeFetch([{ status: 200, body: {} }]);
  await createApi({ fetch, token: () => null }).post("/api/auth/dev-login", { email: "a@example.org" });
  assert.equal("Authorization" in calls[0].init.headers, false);
});

test("the token is read at each request, so a new one is used at once", async () => {
  const { fetch, calls } = fakeFetch([{ status: 200, body: {} }, { status: 200, body: {} }]);
  let t = "first";
  const api = createApi({ fetch, token: () => t });
  await api.get("/a");
  t = "second";
  await api.get("/b");
  assert.deepEqual(calls.map((c) => c.init.headers.Authorization), ["Bearer first", "Bearer second"]);
});

test("an answer is ok, status, body and, on a refusal, the server's sentence", async () => {
  const refusal = { detail: "This needs the admin role in this workspace." };
  const { fetch } = fakeFetch([{ status: 200, body: { x: 1 } }, { status: 403, body: refusal }]);
  const api = createApi({ fetch, token: () => "t" });
  assert.deepEqual(await api.get("/a"), { ok: true, status: 200, body: { x: 1 }, detail: null });
  assert.deepEqual(await api.get("/b"), { ok: false, status: 403, body: refusal, detail: refusal.detail });
});

test("a 403 asks the shell to re-check access; a 401 ends the sign-in; other refusals do neither", async () => {
  const h = counting();
  const { fetch } = fakeFetch([
    { status: 403, body: { detail: "x" } }, { status: 401, body: { detail: "y" } },
    { status: 404, body: { detail: "z" } }, { status: 429, body: { detail: "w" } },
  ]);
  const api = createApi({ fetch, token: () => "t", onForbidden: h.onForbidden, onExpired: h.onExpired });
  await api.get("/1");
  await api.get("/2");
  await api.get("/3");
  await api.post("/4");
  assert.deepEqual(h.seen, { forbidden: 1, expired: 1 });
});

test("a network failure is status 0 with the network sentence, and never throws", async () => {
  const { fetch } = fakeFetch([new TypeError("Failed to fetch")]);
  const r = await createApi({ fetch, token: () => "t" }).get("/a");
  assert.deepEqual(r, { ok: false, status: 0, body: null, detail: NETWORK });
});

test("a body that is not JSON is no body, not a throw", async () => {
  const { fetch } = fakeFetch([{ status: 502 }]);
  const r = await createApi({ fetch, token: () => "t" }).get("/a");
  assert.deepEqual(r, { ok: false, status: 502, body: null, detail: "The request failed (502)." });
});

test("a stream that opens hands back the response itself, unread", async () => {
  const { fetch, calls } = fakeFetch([{ status: 200 }]);
  const r = await createApi({ fetch, token: () => "t" }).stream("/api/chat", { message: "hi" });
  assert.equal(r.ok, true);
  assert.equal(r.response.body, "the stream");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.headers.Authorization, "Bearer t");
  assert.equal(calls[0].init.body, JSON.stringify({ message: "hi" }));
});

test("a stream refused before it starts answers like any refusal, and still asks for the re-check", async () => {
  const h = counting();
  const residency = "This workspace's data must stay in region ksa, and the platform's engine "
    + "here processes in region global, so it cannot run this request.";
  const { fetch } = fakeFetch([{ status: 403, body: { detail: residency } }]);
  const r = await createApi({ fetch, token: () => "t", onForbidden: h.onForbidden })
    .stream("/api/chat", { message: "deep" });
  assert.deepEqual([r.ok, r.status, r.detail], [false, 403, residency]);
  assert.equal(h.seen.forbidden, 1);
});

test("a stream that cannot connect is status 0, not a throw", async () => {
  const { fetch } = fakeFetch([new TypeError("Failed to fetch")]);
  const r = await createApi({ fetch, token: () => "t" }).stream("/api/chat", { message: "hi" });
  assert.deepEqual([r.ok, r.status, r.detail], [false, 0, NETWORK]);
});
