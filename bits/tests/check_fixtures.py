import json, sys, hashlib
from pathlib import Path
from xml.parsers import expat
root = Path(sys.argv[1]); m = json.loads((root/"manifest.json").read_text(encoding="utf-8"))
bad = 0
for e in m["fixtures"]:
    b = (root/e["file"]).read_bytes()
    assert hashlib.sha256(b).hexdigest() == e["sha256"], e["file"]
    if b"\r" in b: print("CR in", e["file"]); bad += 1
    p = expat.ParserCreate(); dtd = []
    p.StartDoctypeDeclHandler = lambda *a: dtd.append(1)
    try:
        p.Parse(b.replace(b"@@CANARY@@", b"/nonexistent").replace(b"@@PORT@@", b"9"), True); ok = True
    except expat.ExpatError as x: ok = False; err = str(x)
    if e["file"].startswith("bit001/"):
        if ok and not dtd: print("BIT001 fixture parses cleanly without DTD:", e["file"])
    elif not ok: print("NOT well-formed:", e["file"], err); bad += 1
print("checked", len(m["fixtures"]), "bad", bad)
