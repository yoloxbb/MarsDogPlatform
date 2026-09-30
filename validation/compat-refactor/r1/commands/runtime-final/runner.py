import subprocess,sys
for action in ("build","doctor","smoke"):
 subprocess.run([sys.executable,"-B","tools/marsdog.py",action],check=True)
