"""INV-AND-19 incident regression: actual MainActivity with lazy PhoneWindow decor, no device claim."""
from pathlib import Path
import os, subprocess, tempfile, unittest
ROOT=Path(os.environ.get('APP_CONTRACT_ROOT',Path(__file__).resolve().parents[1]))
HERE=Path(__file__).resolve().parent/'android_login_host'
JDK=Path('/home/dwl/android-tools/jdk-17.0.20.1+1')
class FreshDecorStartup(unittest.TestCase):
    def test_actual_fresh_activity_api26_27_30_35_36(self):
        dependencies=Path(os.environ.get('ANDROID_HOST_DEPENDENCIES_ROOT','/data/git/ai-control-android-ux-package'))
        jar=dependencies/'android/policy/build/libs/policy.jar'
        self.assertTrue(jar.is_file(),'Existing policy fixture jar required; no downloads')
        jsonjar=sorted(Path('/home/dwl/.gradle/caches/modules-2/files-2.1/org.json/json').glob('*/*/*.jar'))[-1]
        runtime=[]
        for artifact in ['org.jetbrains.kotlin/kotlin-stdlib','org.jetbrains.kotlinx/kotlinx-coroutines-core-jvm','org.jetbrains.kotlinx/kotlinx-coroutines-android']:
            runtime.extend(sorted((Path('/home/dwl/.gradle/caches/modules-2/files-2.1')/artifact).glob('*/*/*.jar')))
        cp=os.pathsep.join(map(str,[jar,jsonjar,dependencies/'android/updater/build/intermediates/built_in_kotlinc/debug/compileDebugKotlin/classes',*runtime,Path('/home/dwl/android-tools/sdk/platforms/android-36/android.jar')]))
        with tempfile.TemporaryDirectory(prefix='fresh-decor-') as directory:
            temp=Path(directory)
            window=(HERE/'stubs/android/view/Window.java').read_text()
            window=window.replace('return new WindowInsetsController(this);','if(root==null)throw new NullPointerException("PhoneWindow: DecorView not installed");return new WindowInsetsController(this);')
            window=window.replace('return root;','if(root==null)root=new View(null);return root;')
            (temp/'Window.java').write_text(window)
            (temp/'UpdatesActivity.java').write_text('package ru.dewil.aicontrol; public class UpdatesActivity extends androidx.activity.ComponentActivity {}')
            (temp/'StartupProbe.java').write_text('package ru.dewil.aicontrol; public class StartupProbe { public static void main(String[] args){MainActivity activity=new MainActivity();try{activity.onCreate(null);if(activity.getWindow().root==null)throw new AssertionError("Content absent after fresh onCreate");System.out.println("PASS fresh decor SDK "+android.os.Build.VERSION.SDK_INT);}finally{activity.onDestroy();}}}')
            source=Path(os.environ.get('ANDROID_STARTUP_MAIN_SOURCE',ROOT/'android/app/src/main/java/ru/dewil/aicontrol/MainActivity.java'))
            # javac requires the production public class basename, including saved baseline.
            (temp/'MainActivity.java').write_text(source.read_text())
            sources=[p for p in HERE.glob('stubs/**/*.java') if p.name!='Window.java']+list(temp.glob('*.java'))
            subprocess.run([str(JDK/'bin/javac'),'-d',directory,'-cp',cp,*map(str,sources)],check=True)
            failures=[]
            for sdk in [26,27,30,35,36]:
                result=subprocess.run([str(JDK/'bin/java'),'-Dfixture.sdk='+str(sdk),'-cp',directory+os.pathsep+cp,'ru.dewil.aicontrol.StartupProbe'],capture_output=True,text=True)
                if result.returncode:failures.append(f'SDK{sdk}: '+result.stderr.strip())
            self.assertEqual(failures,[], '\n'.join(failures))
    def test_updates_has_no_window_controller_startup_access(self):
        source=(ROOT/'android/app/src/main/java/ru/dewil/aicontrol/UpdatesActivity.kt').read_text()
        self.assertNotIn('getInsetsController',source,'Supplemental UpdatesActivity sweep: review lazy-decor access if introduced')
if __name__=='__main__':unittest.main()
