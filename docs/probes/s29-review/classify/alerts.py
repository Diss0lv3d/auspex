import sys, json, time
sys.path.insert(0, "/home/burhan/auspex-new")
from auspex.alerts.normalizer import normalize
from auspex.classify.classifier import classify
from auspex.modes.resolver import resolve_mode
def show(label, obj, raw=None):
    s = raw if raw is not None else json.dumps(obj)
    t0 = time.perf_counter()
    try:
        e = normalize(s)
        out = dict(name=e.name, sev=e.severity, src=e.src, dst=e.dst, ts=e.timestamp, cmd=(e.cmdline or "")[:40] or None, parsed=e.parsed, notes=e.notes)
    except Exception as ex:
        out = f"EXC {type(ex).__name__}: {ex}"
    dt = (time.perf_counter()-t0)*1000
    c = classify(s).category.value
    m = resolve_mode(s, ()).value
    print(f"[{dt:7.1f}ms] {label}: classify={c} mode={m}\n    {str(out)[:300]}")

show("ECS rule.name empty -> ?", {"host":{"name":"dc01"},"rule":{"name":""},"event":{"severity":73}})
show("ECS rule.name null", {"host":{"name":"dc01"},"rule":{"name":None},"message":"x"})
show("ECS no rule, has message", {"host":{"name":"dc01"},"user":{"name":"bob"},"message":"Suspicious LSASS access","event":{"action":"lsass-access"}})
show("nested alert.name (generic)", {"alert":{"name":"Beacon detected","severity":"high"},"host":"ws-12"})
show("nested detection.name", {"detection":{"name":"Mimikatz","severity":"high"}})
show("nested threat.name", {"threat":{"name":"Qakbot"},"severity":"high"})
show("suricata EVE", {"event_type":"alert","src_ip":"10.0.0.1","dest_ip":"10.0.0.2","alert":{"signature":"ET TROJAN x","severity":1}})
show("kibana.alert.rule.name", {"kibana":{"alert":{"rule":{"name":"Elastic rule"},"severity":"high"}},"host":{"name":"dc01"}})
show("flattened dotted literal keys", {"rule.name":"Dotted rule","source.ip":"10.1.2.3","destination.ip":"10.1.9.9","host.name":"dc01"})
show("top name empty string -> rule", {"name":"","rule":{"name":"R"}})
show("top name whitespace", {"name":"   ","rule":{"name":"R"}})
show("top name is list", {"name":["a","b"],"rule":{"name":"R"}})
show("top name is dict", {"name":{"first":"x"},"title":"T"})
show("top name is int 0", {"name":0,"title":"T"})
show("top name is bool", {"name":False,"title":"T"})
show("top Name capitalised", {"Name":"Cap","rule":{"name":"R"}})
show("both name and Name", {"Name":"Cap","name":"low"})
show("ECS source is string + source.ip", {"source":"winlogbeat","source.ip":"10.1.2.3"})
show("ECS source.ip list", {"source":{"ip":["10.1.2.3","10.1.2.4"]}})
show("ECS source.ip nested object", {"source":{"ip":{"v4":"10.1.2.3"}}})
show("ECS source.ip number", {"source":{"ip":167838211}})
show("Graph processCommandLine null", {"title":"T","evidence":[{"processCommandLine":None},{"processCommandLine":"cmd /c whoami"}]})
show("Graph createdDateTime list", {"title":"T","createdDateTime":["a","b"]})
show("Graph alert with top-level evidence names", {"title":"Graph T","evidence":[{"@odata.type":"#microsoft.graph.security.deviceEvidence","deviceDnsName":"dc01","name":"x"}]})
show("rule string + rule.name", {"rule":"R-string"})
show("rule is dict without name, signature in it", {"rule":{"id":"1","signature":"SIG"}})
show("source.ip before src", {"src":"1.1.1.1","source":{"ip":"2.2.2.2"}})
show("huge value", {"rule":{"name":"A"*90000}})
show("deep nesting 5000", None, raw='{"a":' + "["*5000 + "]"*5000 + "}")
show("deep dict nesting 900", None, raw='{"a":' + '{"a":'*900 + '1' + '}'*901)
show("top-level array", [{"rule":{"name":"R"}}])
show("invalid json", None, raw='{"rule": {"name": "R"')
show("NaN / Infinity", None, raw='{"name": NaN, "severity": Infinity, "confidence": -Infinity}')
show("severity big int", {"name":"x","severity":10**400})
show("confidence huge", None, raw='{"name":"x","confidence": 1e400}')
show("timestamp field named time in nested process", {"rule":{"name":"R"},"process":{"start":{"time":"PROC"}},"@timestamp":"TS"})
