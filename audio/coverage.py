"""Which library items have a matching public-domain recording (by translation), independent of whether
the audio has actually been fetched/cut yet. Selector phase 1 uses this to post only audio-ready items first."""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from prepare_audio import source_for, CFG

def is_covered(item):
    """Only sources already confirmed on a LibriVox page (status "found") count for phase 1.
    "unverified" sources (e.g. letters 66+) move to phase 1 automatically once `resolve` confirms them."""
    s, ch = source_for(item)
    if not s: return False
    return CFG[s].get("status") == "found"

def audio_ready_ids(items):
    return {i["id"] for i in items if is_covered(i)}
