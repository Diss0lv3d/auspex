import sys, time, json
sys.path.insert(0, "/home/burhan/auspex-new")
from auspex.classify import classifier as C
from auspex.classify.classifier import classify, _IDENTITY_RE, _NOTE_ASK_RE, _NOTE_REQUEST_RE
from auspex.modes.resolver import resolve_mode
from auspex.alerts.normalizer import normalize

def t(label, fn, s):
    t0 = time.perf_counter()
    try:
        r = fn(s)
    except Exception as e:
        r = f"EXC {type(e).__name__}: {e}"
    dt = (time.perf_counter() - t0) * 1000
    flag = "  <-- SLOW" if dt > 50 else ""
    print(f"{dt:9.1f} ms  len={len(s):6d}  {label}: {str(r)[:60]!r}{flag}")

N = 100_000
cases = {
  "spaces": " " * N,
  "add a a a": "add " + "a " * (N//2 - 4) + "x",
  "add the x many": ("add the " * (N // 8)) + "x",
  "please please": "please " * (N // 7) + "x",
  "can you can you": "can you " * (N // 8) + "x",
  "note note": "note " * (N // 5),
  "tag ... with a": "tag " + "with a " * (N // 7),
  "tag tag": "tag " * (N//4),
  "annotate": "annotate " * (N//9),
  "jot down": "jot it down " * (N//12),
  "record": "record " * (N//7),
  "update notes": "update the notes " * (N//17),
  "with a with a": "with a " * (N//7),
  "pls": "pls " * (N//4),
  "hey,:": "hey , : " * (N//8),
  "log a a a": "log " + "a "*(N//2 - 3) + "x",
  "add + spaces": "add" + " "*N + "x",
  "add a + spaces each": "add" + ("a" + " " * 50) * (N//51),
  "newline mix": ("add\n" * (N//4)),
  "unicode spaces": "add" + "　" * N + "note",
  "json": json.dumps({"k%d" % i: "add a note please note " for i in range(2500)}),
}
for label, s in cases.items():
    t("ASK " + label, lambda x: bool(_NOTE_ASK_RE.search(x)), s)
    t("REQ " + label, lambda x: bool(_NOTE_REQUEST_RE.search(x)), s)
    t("IDENT(raw, no len cap) " + label, lambda x: bool(_IDENTITY_RE.match(x)), s[:2000])
    t("classify " + label, lambda x: classify(x).category, s)
    t("resolve " + label, lambda x: resolve_mode(x, ()), s)
