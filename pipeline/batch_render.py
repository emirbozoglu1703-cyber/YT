"""Klasörleri paralel render eder: python pipeline/batch_render.py -j 3 work/batch/*/*  (short.mp4 olanları atlar, --force ile yeniden)"""
import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

ap = argparse.ArgumentParser()
ap.add_argument("dirs", nargs="+")
ap.add_argument("-j", type=int, default=3)
ap.add_argument("--force", action="store_true")
a = ap.parse_args()
todo = [d for d in a.dirs if os.path.exists(os.path.join(d, "staging.json")) and (a.force or not os.path.exists(os.path.join(d, "short.mp4")))]
tools = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools.py")


def run(d):
    r = subprocess.run([sys.executable, tools, "render", d], capture_output=True, text=True)
    return d, r.returncode, (r.stdout + r.stderr)[-300:]


print(f"{len(todo)} video render edilecek ({a.j} paralel)", flush=True)
with ThreadPoolExecutor(a.j) as ex:
    for i, (d, rc, out) in enumerate(ex.map(run, todo), 1):
        print(f"[{i}/{len(todo)}] {d}: {'OK' if rc == 0 else 'HATA ' + out}", flush=True)
