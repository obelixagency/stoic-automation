"""One-off: upload brand/fb_cover.jpg as the Facebook Page cover. Prints PASS/FAIL and a short code only."""
import os, requests
import meta_api as M
pid = os.environ["FB_PAGE_ID"]; tok = M.page_token()
if not tok:
    print("FAIL no page token"); raise SystemExit(1)
with open("brand/fb_cover.jpg", "rb") as f:
    r = requests.post(f"{M.GRAPH}/{pid}/photos", data={"published": "false", "access_token": tok}, files={"source": f}, timeout=120)
d = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
if r.status_code >= 400 or "id" not in d:
    print("FAIL upload", r.status_code, d.get("error", {}).get("code")); raise SystemExit(1)
r2 = requests.post(f"{M.GRAPH}/{pid}", data={"cover": d["id"], "offset_y": 0, "access_token": tok}, timeout=60)
d2 = r2.json()
print("PASS cover set" if r2.status_code < 400 and d2.get("success", True) else f'FAIL set {r2.status_code} {d2.get("error", {}).get("code")}')
raise SystemExit(0 if r2.status_code < 400 else 1)
