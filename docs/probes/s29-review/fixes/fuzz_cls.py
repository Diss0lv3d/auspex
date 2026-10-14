import importlib.util, sys, random, time, itertools
sys.path.insert(0, '.')
S = sys.argv[1]
spec = importlib.util.spec_from_file_location("cls_old", S + "/classifier_old.py")
old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
from auspex.classify import classifier as new
OI, NI = old._IDENTITY_RE, new._IDENTITY_RE
ON, NN = old._NOTE_REQUEST_RE, new._NOTE_REQUEST_RE
toks_lead = ["hey","hi","so","ok","okay","btw","quick question","curious","sorry if this is random","but","but ",
             "out of curiosity","just curious","hiya","sorry","s","o"]
ws = [" ", "  ", "\t", "　", "\n", "\xa0", ""]
punct = [",", ":", "-", "–", "—", ",,", "?", ".", "!"]
bodies = ["who are you","who made you","what model are you","are you gpt-4","is this claude","introduce yourself",
          "what's under the hood","which llm is this","r u chatgpt","x","tell me about yourself","what are you built on", "-who are you"]
nbodies = ["add a note on it","annotate x","note on it","note that","tag x with a note","record on x","please add a note",
           "can you add a note","update notes on x","jot it down for x","x","kindly note foo","note: x","note to x"]
random.seed(7)
diff = 0; n = 0
def gen(bset, k):
    parts = []
    for _ in range(random.randint(0, k)):
        parts.append(random.choice(toks_lead))
        for _ in range(random.randint(0,2)):
            parts.append(random.choice(ws + punct))
    parts.append(random.choice(bset))
    for _ in range(random.randint(0,2)):
        parts.append(random.choice(ws + punct))
    s = "".join(parts)
    if random.random() < 0.3:
        s = random.choice(ws) + s
    return s
for i in range(200000):
    s = gen(bodies, 3)
    if len(s) > 45: continue
    n += 1
    a = bool(OI.match(s)); b = bool(NI.match(s))
    if a != b:
        diff += 1
        if diff < 10: print("ID DIFF", repr(s), a, b)
    t = gen(nbodies, 2)
    if len(t) > 60: continue
    a = bool(ON.search(t)); b = bool(NN.search(t))
    if a != b:
        diff += 1
        if diff < 10: print("NOTE DIFF", repr(t), a, b)
print("checked", n, "diffs", diff)
