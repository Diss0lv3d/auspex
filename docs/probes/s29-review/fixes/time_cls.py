import sys, time, random
sys.path.insert(0, '.')
from auspex.classify import classifier as new
from auspex.classify import classify
I = new._IDENTITY_RE; N = new._NOTE_REQUEST_RE
def t(fn, s, reps=3):
    best = 1e9
    for _ in range(reps):
        a = time.perf_counter(); fn(s); best = min(best, time.perf_counter()-a)
    return best*1000
cands = [
 "who are you" + " "*68 + "x",
 "who are you" + " ?"*34 + "x",
 "who are you" + "\t"*68 + "x",
 " "*79 + "x",
 "hi " * 26 + "x",
 "hi but " * 11 + "x",
 "hi, but  " * 8 + "x",
 "are you gpt" + " or x"*13 + "!",
 "are you gpt" + "-"*68 + "!",
 "what is the model is is is is is is is is is is is is is is is is is is is is x",
 "what model" + " is"*23 + " x",
 "what ai model" + " are"*16 + " x",
 "what's the model version does does does does does does does does does does q",
 "is this claude or " + "x"*60 + " !",
 "sorry if this is random " * 3 + "x",
 "ok okay ok okay ok okay ok okay ok okay ok okay ok okay ok okay ok okay ok x",
 "so so so so so so so so so so so so so so so so so so so so so so so so so x",
 "what are you" + " "*30 + "?"*30 + " x",
]
for c in cands:
    c = c[:80]
    print(f"{t(I.match, c):8.3f} ms  classify {t(classify, c):8.3f} ms  {c!r}")
# random search on <=80 char strings
alpha = ["hi","hey","so","ok","but","who","are","you","what","is","model","the","ai","llm","this","or","gpt","claude","x"," ","  ",",","-","?","!","."," is"," are"]
random.seed(3)
worst = (0, "")
for i in range(30000):
    s = "".join(random.choice(alpha) for _ in range(random.randint(5, 40)))[:80]
    d = t(I.match, s, 1)
    if d > worst[0]: worst = (d, s)
print("random worst", worst)
# note request
for c in ["hey" + " "*32000 + "x", " "*32000 + "x", "please " * 4500 + "x", "please" + " "*32000 + "x",
          "can you " * 4000 + "x", "tag " + "x"*31990, "add " + "a "*15990 + "x", "annot" + "a"*31990 + " x",
          "add" + " the"*7990 + " x", "hi:" + " "*31990 + "x", "hey ," + " "*31990 + "x", "\n"*32000+"x"]:
    print(f"note {t(N.search, c):8.3f} ms  len={len(c)} {c[:20]!r}")
