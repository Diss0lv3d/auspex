import importlib.util, sys, json
sys.path.insert(0, '.')
S = sys.argv[1]
spec = importlib.util.spec_from_file_location("norm_old", S + "/normalizer_old.py")
old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
from auspex.alerts import normalizer as new
shapes = {
 "elastic_security": {"@timestamp": "2026-10-01T00:00:00Z", "kibana": {"alert": {"rule": {"name": "Rule X", "severity": "high"}, "severity": "high", "reason": "process event"}},
                      "host": {"name": "ws-12"}, "user": {"name": "bob"}, "process": {"name": "powershell.exe", "command_line": "powershell -enc ..."}},
 "elastic_dotted": {"kibana.alert.rule.name": "Rule X", "kibana.alert.severity": "high", "host.name": "ws-12", "kibana.alert.original_event.action": "exec"},
 "elastic_signal_7x": {"signal": {"rule": {"name": "Rule Old", "severity": "medium"}}, "host": {"name": "ws-12"}},
 "suricata_eve": {"timestamp": "2026-10-01T00:00:00Z", "event_type": "alert", "src_ip": "10.0.0.1", "dest_ip": "203.0.113.5",
                  "alert": {"action": "allowed", "signature_id": 2024217, "signature": "ET MALWARE Beacon", "category": "A Network Trojan", "severity": 1}},
 "graph_alert": {"title": "Suspicious PowerShell", "severity": "high", "hostStates": [{"fqdn": "ws-12"}], "fileStates": [{"name": "evil.ps1"}], "userStates": [{"accountName": "bob"}]},
 "crowdstrike_es": {"metadata": {"eventType": "DetectionSummaryEvent"}, "event": {"DetectName": "Malicious Activity", "ComputerName": "ws-12", "UserName": "bob", "FileName": "x.exe", "Severity": 4}},
 "wazuh": {"rule": {"level": 10, "description": "sshd brute force", "id": "5712"}, "agent": {"id": "001", "name": "web-01"}, "manager": {"name": "wazuh-mgr"}, "decoder": {"name": "sshd"}, "data": {"srcip": "198.51.100.7"}},
 "s1_star": {"ruleInfo": {"name": "STAR rule"}, "agentDetectionInfo": {"name": "DESKTOP-01"}, "alertInfo": {"severity": "High"}},
 "alert_wrap_with_rule": {"alert": {"name": "Alert name"}, "rule": {"name": "Rule name"}},
 "alert_wrap_with_title": {"alert": {"name": "Alert name"}, "title": "Title"},
 "nested_entity_alert": {"host": {"alert": {"name": "host-alert-thing"}}, "title": "Real title"},
 "detection_list": {"detection": [{"ruleName": "YL2 rule", "name": "det-name"}], "type": "RULE_DETECTION"},
 "rule_name_flat_vs_alert": {"rule_name": "Flat rule", "alert": {"name": "Alert name"}},
}
for k, obj in shapes.items():
    t = json.dumps(obj)
    a = old._parse_json(t)["name"]; b = new._parse_json(t)["name"]
    print(f"{k:24} old={a!r:28} new={b!r}{'   <-- CHANGED' if a != b else ''}")
