import sys, time
sys.path.insert(0, "/home/burhan/auspex-new")
from auspex.classify import classifier as C
from auspex.classify.observables import extract
def tm(label, fn, s):
    t0=time.perf_counter(); r=fn(s); dt=(time.perf_counter()-t0)*1000
    print(f"{dt:9.1f} ms len={len(s)} {label} -> {str(r)[:50]!r}")
for n in (8000, 16000, 32000):
    for name, s in (("ascii spaces", "add" + " "*n + "x"), ("ideographic", "add" + "　"*n + "note"), ("plain x+spaces", "x" + " "*n + "x")):
        s = s[:32000]
        tm(f"extract {name}", lambda x: len(extract(x).observables), s)
        tm(f"analytical {name}", C._is_analytical, s)
        tm(f"note {name}", lambda x: C.asks_for_note(x) or C.is_note_request(x), s)
        tm(f"classify {name}", lambda x: C.classify(x).category, s)
