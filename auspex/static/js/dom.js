// The one element factory and lookup every page uses (F4). Props are DOM
// properties (href, rel, className, …), and a string child is appended as a
// text node: nothing here parses HTML (D-053). An absent child (null,
// undefined, false) is skipped, so a card can hold an optional line in place.
export const $ = (id) => document.getElementById(id);

export function el(tag, props = {}, children = []) {
  const e = document.createElement(tag);
  Object.assign(e, props);
  e.append(...children.filter((c) => c !== null && c !== undefined && c !== false));
  return e;
}
