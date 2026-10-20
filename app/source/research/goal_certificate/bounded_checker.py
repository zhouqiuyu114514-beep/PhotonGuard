"""Linux reproduction entry point with wall time, output and memory limits."""
import os, resource, signal, sys
from pathlib import Path

def main():
    pump='--pump' in sys.argv
    cap=(256*1024**2 if pump else 1024**3)
    seconds=60 if pump else 600
    available=int(next(row.split()[1] for row in Path('/proc/meminfo').read_text().splitlines() if row.startswith('MemAvailable:')))*1024
    if cap>available//2:raise SystemExit('RESOURCE_PREFLIGHT_REFUSED: insufficient available RAM; no assembly started')
    resource.setrlimit(resource.RLIMIT_AS,(cap,cap))
    resource.setrlimit(resource.RLIMIT_CPU,(seconds,seconds))
    size=10*1024**2 if pump else 128*1024**2
    resource.setrlimit(resource.RLIMIT_FSIZE,(size,size))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    signal.alarm(seconds)
    from .checker import main as check
    return check()

if __name__=='__main__':raise SystemExit(main())
