"""HTTP layer: polite GET with a small on-disk cache (no API keys, free public endpoints only)."""
import hashlib, json, os, time, threading
import requests

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)
_S = requests.Session()
_S.headers.update({"User-Agent": "Mozilla/5.0 (personal research script; low volume)"})
_lock = threading.Lock()
_last = [0.0]
MIN_GAP = 0.12  # seconds between live requests (politeness)
STATS = {"live": 0, "cached": 0, "errors": 0}


def _key(url, params):
    raw = url + "?" + json.dumps(params or {}, sort_keys=True)
    return os.path.join(CACHE_DIR, hashlib.sha1(raw.encode()).hexdigest() + ".json")


def get_json(url, params=None, ttl=600, timeout=20, retries=2):
    """Return parsed JSON or None. ttl in seconds (0 = always live)."""
    path = _key(url, params)
    if ttl and os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
        try:
            with open(path) as f:
                STATS["cached"] += 1
                return json.load(f)
        except Exception:
            pass
    for attempt in range(retries + 1):
        with _lock:
            gap = time.time() - _last[0]
            if gap < MIN_GAP:
                time.sleep(MIN_GAP - gap)
            _last[0] = time.time()
        try:
            r = _S.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                d = r.json()
                STATS["live"] += 1
                try:
                    with open(path, "w") as f:
                        json.dump(d, f)
                except Exception:
                    pass
                return d
            if r.status_code in (400, 404):
                STATS["errors"] += 1
                return None
        except Exception:
            pass
        time.sleep(0.6 * (attempt + 1))
    STATS["errors"] += 1
    # stale cache fallback
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return None
    return None


def purge(max_age=3 * 86400):
    n = 0
    for fn in os.listdir(CACHE_DIR):
        p = os.path.join(CACHE_DIR, fn)
        if time.time() - os.path.getmtime(p) > max_age:
            os.remove(p); n += 1
    return n
