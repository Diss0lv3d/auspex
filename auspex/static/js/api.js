// The one API client (F4). Every request a page makes goes through it, so the
// bearer header is written here and nowhere else. It does not judge a
// refusal: a 403 is handed to the shell, which asks GET /api/auth/me whether
// this tab may still be here (D-070); a 401 ends the sign-in. `fetch` is
// injected, so tests/js/api.test.mjs drives it under Node.
import { errorText } from "./shell-logic.js";

export function createApi({ fetch, token, onForbidden = () => {}, onExpired = () => {} }) {
  const headers = (json) => {
    const h = json ? { "Content-Type": "application/json" } : {};
    const t = token();
    if (t) h.Authorization = "Bearer " + t;
    return h;
  };
  const refused = (status) => {
    if (status === 401) onExpired();
    else if (status === 403) onForbidden();
  };
  const readBody = async (r) => { try { return await r.json(); } catch (e) { return null; } };

  async function request(method, path, body) {
    let r;
    try {
      r = await fetch(path, {
        method, headers: headers(body !== undefined),
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (e) {
      return { ok: false, status: 0, body: null, detail: errorText(0, null) };
    }
    const parsed = await readBody(r);
    if (!r.ok) refused(r.status);
    return { ok: r.ok, status: r.status, body: parsed, detail: r.ok ? null : errorText(r.status, parsed) };
  }

  return {
    get: (path) => request("GET", path),
    post: (path, body) => request("POST", path, body),
    // Server-sent events: the Response itself, unread, once it streams. A
    // refusal before the stream (the input rail's 400, residency's 403, the
    // usage ceiling's 429) answers like get and post.
    async stream(path, body) {
      let r;
      try {
        r = await fetch(path, { method: "POST", headers: headers(true), body: JSON.stringify(body) });
      } catch (e) {
        return { ok: false, status: 0, body: null, detail: errorText(0, null) };
      }
      if (r.ok) return { ok: true, status: r.status, response: r };
      const parsed = await readBody(r);
      refused(r.status);
      return { ok: false, status: r.status, body: parsed, detail: errorText(r.status, parsed) };
    },
  };
}
