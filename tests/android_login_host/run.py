#!/usr/bin/env python3
"""Execute real MainActivity against bounded host Android doubles, never a device proof.

Dependencies are already-installed JDK/SDK, Gradle policy.jar and org.json cache.
No network or credential store is accessed. Delayed/UI callbacks are queued.
"""
from pathlib import Path
import os
import subprocess
import tempfile
ROOT = Path(os.environ.get('APP_CONTRACT_ROOT', Path(__file__).resolve().parents[2]))
HERE = Path(__file__).resolve().parent
jdk = Path(os.environ.get('JAVA_HOME', '/home/dwl/android-tools/jdk-17.0.20.1+1'))
sdk = Path(os.environ.get('ANDROID_HOME', '/home/dwl/android-tools/sdk'))
cache = Path('/home/dwl/.gradle/caches/modules-2/files-2.1/org.json/json')
json_jars = sorted(cache.glob('*/*/*.jar'))
if not json_jars:
    raise SystemExit('Existing org.json cache absent; no dependencies installed')
jar = ROOT / 'android/policy/build/libs/policy.jar'
if not jar.is_file():
    subprocess.run([str(ROOT/'android/gradlew'), '-p', str(ROOT/'android'), ':policy:jar', '--offline', '--console=plain'], check=True)
cp = os.pathsep.join(map(str,[json_jars[-1],jar,sdk/'platforms/android-36/android.jar']))
with tempfile.TemporaryDirectory(prefix='ai-login-host-') as out:
    sources = sorted(HERE.glob('stubs/**/*.java')) + [HERE/'LoginLifecycleProbe.java', ROOT/'android/app/src/main/java/ru/dewil/aicontrol/MainActivity.java']
    subprocess.run([str(jdk/'bin/javac'), '-d', out, '-cp', cp, *map(str,sources)], check=True)
    failures=[]
    for case in ['initial', 'keepass', 'submit', 'reset', 'updates']:
        result=subprocess.run([str(jdk/'bin/java'), '-cp', out+os.pathsep+cp, 'ru.dewil.aicontrol.LoginLifecycleProbe',case])
        if result.returncode: failures.append(case)
    print('Host contract failures:', ', '.join(failures) if failures else 'none', flush=True)
    raise SystemExit(bool(failures))
