import json, sys
p = "betlib/ratings.py"; s = open(p).read().split("\n")
lk = sys.argv[1]; d = json.loads(sys.argv[2])
for i, l in enumerate(s):
    if l.startswith(f'    "{lk}": dict('):
        s[i] = f'    "{lk}": dict(' + ", ".join(f"{k}={round(v,4) if isinstance(v,float) else v}" for k, v in d.items()) + "),"
open(p, "w").write("\n".join(s))
