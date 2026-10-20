@echo off
wsl.exe -d Ubuntu -u zhou --cd /home/zhou/projects/PhotonGuard-development --exec /home/zhou/projects/PhotonGuard/.runtime/run-python -B tools/serve_ai_repair.py --rules-only
