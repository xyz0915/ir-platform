import urllib.request, json, ssl

ctx = ssl._create_unverified_context()
base = "http://localhost:8000"

# Login
login_data = json.dumps({"username": "admin", "password": "admin123"}).encode()
req = urllib.request.Request(f"{base}/api/auth/login", data=login_data,
    headers={"Content-Type": "application/json"})
TOKEN = json.loads(urllib.request.urlopen(req, context=ctx, timeout=5).read())["data"]["token"]
hdr = {"Authorization": f"Bearer {TOKEN}"}

event_id = "cmfile_hashes99"

# 1. Main event
print("=== Main Event ===")
req = urllib.request.Request(f"{base}/api/analysis/events/{event_id}", headers=hdr)
d = json.loads(urllib.request.urlopen(req, timeout=5).read()).get("data", {})
print(f"  event_type: {d.get('event_type')}")
print(f"  evidence: {str(d.get('evidence', ''))[:300]}")
print(f"  ai_verdict: {str(d.get('ai_verdict', ''))[:100]}")
print(f"  related_events: {str(d.get('related_events', ''))[:100]}")

# 2. Display
print("\n=== Display ===")
req = urllib.request.Request(f"{base}/api/analysis/events/{event_id}/display", headers=hdr)
data = json.loads(urllib.request.urlopen(req, timeout=5).read())
disp = data.get("data", {})
ev = disp.get("evidence_views", {})
print(f"  normalized: {str(ev.get('normalized', {}))[:200]}")
print(f"  required keys: {list(disp.get('required', {}).keys())[:8]}")

# 3. Timeline
print("\n=== Timeline ===")
req = urllib.request.Request(f"{base}/api/analysis/events/timeline", headers=hdr)
data = json.loads(urllib.request.urlopen(req, timeout=10).read())
tl = data.get("data", {})
print(f"  total_groups: {tl.get('total_groups')}")
print(f"  events count: {len(tl.get('events', []))}")

# 4. Process Tree
print("\n=== Process Tree ===")
req = urllib.request.Request(f"{base}/api/analysis/events/{event_id}/process-tree", headers=hdr)
data = json.loads(urllib.request.urlopen(req, timeout=5).read())
pt = data.get("data", {})
print(f"  tree: {str(pt.get('tree', []))[:200]}")

# 5. Related Events
print("\n=== Related Events ===")
req = urllib.request.Request(f"{base}/api/analysis/events/{event_id}/related", headers=hdr)
data = json.loads(urllib.request.urlopen(req, timeout=5).read())
re = data.get("data", {})
print(f"  events: {str(re.get('events', []))[:200]}")
