import json, sys
sys.path.insert(0, ".")
from core.client import make_session
from core.constants import PLATFORMS
from core.utils import _build_label_map

s = make_session("cn")
base = PLATFORMS["cn"]["base_url"]
r = s.get(f"{base}/view/survey/detail", params={"id": 91986})
d = json.loads(r.text)["data"]
qs = d.get("questions", [])
lm = _build_label_map(qs)

for label in ["Q1", "Q16", "Q24", "Q27"]:
    idx = lm.get(label)
    q = qs[idx]
    print(f"=== {label} [{q['type']}] ===")
    print("logic:", json.dumps(q.get("logic"), ensure_ascii=False, indent=2))
    opts = q.get("options") or []
    print("options:", [f"{o['id']}:{o.get('text','')}" for o in opts])
    subs = q.get("subQuestions") or []
    if subs:
        print("subQuestions:", [f"{sq['id']}:{sq.get('title','')[:20]}" for sq in subs])
    print()