"""R2 preflight: upload a tiny test image, fetch it over the public URL, delete it. Prints PASS/FAIL only."""
import os, tempfile, requests, r2
p = os.path.join(tempfile.mkdtemp(), "r2-preflight.jpg")
open(p, "wb").write(b"\xff\xd8\xff\xd9")
c = r2._client()
try:
    url = r2.ensure(p, client=c)
    r = requests.get(url, timeout=30)
    print("PASS upload+public fetch" if r.status_code == 200 else f"FAIL public fetch http {r.status_code}")
    ok = r.status_code == 200
finally:
    try: c.delete_object(Bucket=r2.BUCKET, Key="r2-preflight.jpg")
    except Exception: print("note: cleanup failed")
raise SystemExit(0 if ok else 1)
