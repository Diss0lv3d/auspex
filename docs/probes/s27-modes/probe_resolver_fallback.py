"""S27 — the mode resolver's default, measured in code before it is changed.

IDEAS.md: a non-security question ("write me a status update for my manager")
resolves to `threat_intel`, whose contract it cannot meet. S26 measured it 4/4,
and S27's drift battery 4/4 again. The candidate is a fallback mode for deep
questions with no security signal.

This battery is labeled by hand: security questions phrased so that most of
them carry NO threat-intel keyword (the case a lexicon would miss), and plainly
non-security questions. For each one it prints the 92/8 category and what the
resolver decides. It runs the code only, with no model and no network, so it
can be run before and after a change and diffed.

Run:  .venv/bin/python docs/probes/s27-modes/probe_resolver_fallback.py [--held-out | --held-out-2]
"""

import sys

sys.path.insert(0, "/home/burhan/auspex-new")

from auspex.classify import classify, shortcut_answer  # noqa: E402
from auspex.modes import resolve_mode  # noqa: E402

SECURITY = [
    "How should we harden our nginx configuration?",
    "A laptop with customer data was left in a taxi overnight. What do we do now?",
    "Someone in finance got a call from the 'CEO' asking for an urgent wire transfer. "
    "How do we respond?",
    "What logs should we keep to investigate a domain controller compromise?",
    "Our users keep reusing passwords. What policy should we set?",
    "How do we rotate the service account keys on our build server?",
    "Explain how Kerberos delegation can be abused.",
    "Is it safe to let contractors use their own laptops on our network?",
    "What should our incident response playbook for ransomware include?",
    "Write a detection rule for suspicious PowerShell usage.",
    "How do I tell if a USB drive someone found in the car park is malicious?",
    "Should we block TOR exit nodes at the perimeter?",
    "How can we reduce our attack surface on AWS?",
    "What's the best way to segment an OT network from the office LAN?",
    "Draft an email warning staff about a fake invoice scam going around.",
    "How long should we retain firewall logs for an investigation?",
    "Our SSO provider had an outage this morning. What are the risks for us?",
    "Why would a process inject into explorer.exe?",
    "An ex-employee still has access to our shared drive. What should I do first?",
    "We think someone is copying files off the HR server at night. How do we confirm it?",
]

NON_SECURITY = [
    "Write me a status update for my manager about this week.",
    "Can you help me plan the agenda for our team offsite next month?",
    "Explain the difference between TCP and UDP for a new hire.",
    "Draft a polite email declining a meeting invite for Thursday.",
    "How do I convert a JSON file to CSV in Python?",
    "What's a good way to structure a one-on-one with a new team member?",
    "Translate 'good morning, how was your weekend' into Arabic.",
    "Give me three ideas for a team lunch that work for vegetarians.",
    "How many working hours are there in a fortnight?",
    "Rewrite this sentence to sound more professional: we done the thing late.",
]


def run(label: str, prompts: list[str]) -> list[str]:
    print(f"\n{label}")
    modes = []
    for p in prompts:
        c = classify(p)
        if shortcut_answer(c) is not None:
            print(f"  SHORTCUT {c.category.value:12} {p[:70]}")
            continue
        mode = resolve_mode(p, c.observables).value
        modes.append(mode)
        print(f"  {mode:18} {p[:80]}")
    return modes


def main() -> None:
    # Both JSON batteries were written by independent agents that never saw the
    # vocabulary. `--held-out` (the first) was out-of-sample for approach 1 and
    # then informed approach 2, so it is training data now. `--held-out-2` was
    # written AFTER approach 2 was frozen: the honest number for approach 2.
    files = {"--held-out": "heldout-battery.json", "--held-out-2": "heldout2-battery.json"}
    flag = next((f for f in files if f in sys.argv[1:]), None)
    if flag:
        import json
        from pathlib import Path

        battery = json.loads((Path(__file__).parent / files[flag]).read_text())
        security, non_security = battery["security"], battery["non_security"]
    else:
        security, non_security = SECURITY, NON_SECURITY
    sec = run("security questions (should never lose their structure)", security)
    non = run("non-security questions", non_security)
    print(f"\nsummary ({files[flag] if flag else 'in-sample battery'})")
    print(f"  security deep turns: {len(sec)}; resolved to general: "
          f"{sec.count('general')}; threat_intel: {sec.count('threat_intel')}")
    print(f"  non-security deep turns: {len(non)}; resolved to general: "
          f"{non.count('general')}; threat_intel: {non.count('threat_intel')}")


if __name__ == "__main__":
    main()
