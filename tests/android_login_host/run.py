#!/usr/bin/env python3
"""Execute real MainActivity against bounded host Android doubles, never a device proof.

Dependencies are already-installed JDK/SDK, Gradle policy.jar and org.json cache.
No network or credential store is accessed. Delayed/UI callbacks are queued.
"""
from pathlib import Path
import os
import subprocess
import tempfile
from theme_contract import properties
ROOT = Path(os.environ.get('APP_CONTRACT_ROOT', Path(__file__).resolve().parents[2]))
HERE = Path(__file__).resolve().parent
jdk = Path(os.environ.get('JAVA_HOME', '/home/dwl/android-tools/jdk-17.0.20.1+1'))
sdk = Path(os.environ.get('ANDROID_HOME', '/home/dwl/android-tools/sdk'))
cache = Path('/home/dwl/.gradle/caches/modules-2/files-2.1/org.json/json')
json_jars = sorted(cache.glob('*/*/*.jar'))
if not json_jars:
    raise SystemExit('Existing org.json cache absent; no dependencies installed')
jar = ROOT / 'android/policy/build/libs/policy.jar'
kotlin_classes=ROOT/'android/app/build/intermediates/built_in_kotlinc/debug/compileDebugKotlin/classes'
if True: # Gradle tracks source freshness; never execute a stale UpdatesActivity class.
    subprocess.run([str(ROOT/'android/gradlew'),'-p',str(ROOT/'android'),':app:compileDebugKotlin','--offline','--console=plain'],check=True)
updater_classes=ROOT/'android/updater/build/intermediates/built_in_kotlinc/debug/compileDebugKotlin/classes'
runtime=[]
for artifact in ['org.jetbrains.kotlin/kotlin-stdlib','org.jetbrains.kotlinx/kotlinx-coroutines-core-jvm','org.jetbrains.kotlinx/kotlinx-coroutines-android']:
    runtime.extend(sorted((Path('/home/dwl/.gradle/caches/modules-2/files-2.1')/artifact).glob('*/*/*.jar')))
if not jar.is_file():
    subprocess.run([str(ROOT/'android/gradlew'), '-p', str(ROOT/'android'), ':policy:jar', '--offline', '--console=plain'], check=True)
cp = os.pathsep.join(map(str,[json_jars[-1],jar,kotlin_classes,updater_classes,*runtime,sdk/'platforms/android-36/android.jar']))
with tempfile.TemporaryDirectory(prefix='ai-login-host-') as out:
    sources = sorted(HERE.glob('stubs/**/*.java')) + [HERE/'LoginLifecycleProbe.java', HERE/'CompactUpdatesProbe.java', HERE/'NativeDarkProbe.java',HERE/'InstalledVersionProbe.java', ROOT/'android/app/src/main/java/ru/dewil/aicontrol/MainActivity.java']
    subprocess.run([str(jdk/'bin/javac'), '-d', out, '-cp', cp, *map(str,sources)], check=True)
    failures=[]
    theme_properties=properties(ROOT)
    for case in ['initial', 'keepass', 'submit', 'reset', 'updates']:
        result=subprocess.run([str(jdk/'bin/java'), *theme_properties, '-cp', out+os.pathsep+cp, 'ru.dewil.aicontrol.LoginLifecycleProbe',case])
        if result.returncode: failures.append(case)
    for case in ['viewport','palette','access']:
        result=subprocess.run([str(jdk/'bin/java'), *theme_properties, '-cp', out+os.pathsep+cp, 'ru.dewil.aicontrol.CompactUpdatesProbe',case])
        if result.returncode: failures.append('compact-'+case)
    result=subprocess.run([str(jdk/'bin/java'),*theme_properties,'-cp',out+os.pathsep+cp,'ru.dewil.aicontrol.NativeDarkProbe'])
    if result.returncode:failures.append('native-dark')
    for sdk_level in [26,28]:
        for case in ['installed','unknown','empty','invalid','missing','observer','reopen']:
            result=subprocess.run([str(jdk/'bin/java'),*theme_properties,'-Dfixture.sdk='+str(sdk_level),'-cp',out+os.pathsep+cp,'ru.dewil.aicontrol.InstalledVersionProbe',case])
            if result.returncode:failures.append('installed-'+str(sdk_level)+'-'+case)
    print('Host contract failures:', ', '.join(failures) if failures else 'none', flush=True)
    raise SystemExit(bool(failures))
