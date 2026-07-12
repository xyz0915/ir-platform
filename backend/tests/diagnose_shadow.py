"""Diagnose shadow detection with Agent JSON."""
import json
import sys
sys.path.insert(0, '.')

from app.analysis.service_risk_analyzer import ServiceRiskAnalyzer

# Load real Agent JSON
with open('../agent/dist/DESKTOP-NCR4EED_20260712_220840.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Extract services
services = ServiceRiskAnalyzer._extract_services(data)
print(f"Extracted {len(services)} services")

# Check path field
empty_path = sum(1 for s in services if not s.get('path'))
print(f"Services with empty path: {empty_path}")

# Show some paths
with_path = [s for s in services if s.get('path')]
print(f"Services with path: {len(with_path)}")
for s in with_path[:10]:
    name = s['name']
    raw = s['path']
    norm = ServiceRiskAnalyzer._normalize_path(raw)
    in_trusted = any(norm.startswith(tp) for tp in __import__('app.analysis.service_constants', fromlist=['TRUSTED_PATHS']).TRUSTED_PATHS)
    print(f"  {name}: raw={raw[:80]}")
    print(f"    norm={norm[:80]} trusted={in_trusted}")

# Run shadow detection
shadow = ServiceRiskAnalyzer._detect_shadow(services)
print(f"\nShadow detections: {len(shadow)}")

# Reasons breakdown
from collections import Counter
reasons = Counter()
for d in shadow:
    detail = d['detail']
    if '路径不在可信路径中' in detail:
        reasons['untrusted_path'] += 1
    if '相似' in detail or '伪装' in detail:
        reasons['name_similarity'] += 1
    if '可疑关键词' in detail:
        reasons['suspicious_keyword'] += 1

print(f"Reason breakdown: {dict(reasons)}")

# Count non-shadow services
shadow_names = {d['service_name'] for d in shadow}
print(f"Services NOT flagged shadow: {len(services) - len(shadow)}")
