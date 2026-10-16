// The one element factory (F4), under Node with a stand-in document: el()
// needs only createElement and the element's append, and $ only
// getElementById. Strings must reach append() as strings — the DOM makes each
// one a text node, which is what keeps model and feed text inert.
//
//   node --test tests/js/dom.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { el, $ } from "../../auspex/static/js/dom.js";

globalThis.document = {
  createElement(tag) {
    return { tag, appended: [], append(...c) { this.appended.push(...c); } };
  },
  getElementById(id) { return { id }; },
};

test("props are set as properties on the element", () => {
  const a = el("a", { href: "https://example.org/", className: "x" });
  assert.equal(a.tag, "a");
  assert.equal(a.href, "https://example.org/");
  assert.equal(a.className, "x");
});

test("a string child is passed as a string, so the DOM makes it a text node, never markup", () => {
  const p = el("p", {}, ['<img src=x onerror="alert(1)">']);
  assert.deepEqual(p.appended, ['<img src=x onerror="alert(1)">']);
});

test("absent children are skipped in place; zero and empty strings are kept", () => {
  const child = el("span");
  const d = el("div", {}, ["a", null, child, undefined, false, 0, ""]);
  assert.deepEqual(d.appended, ["a", child, 0, ""]);
});

test("with no props and no children it is a bare element", () => {
  assert.deepEqual(el("div").appended, []);
});

test("$ looks an element up by its id", () => {
  assert.deepEqual($("status"), { id: "status" });
});
