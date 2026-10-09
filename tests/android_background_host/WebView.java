package android.webkit;
import java.util.*;
public class WebView extends android.view.View {
 public static List<WebView> instances=new ArrayList<>();public static List<String> events=new ArrayList<>();public static String evalResult=null;
 public static class Eval {public String script;public ValueCallback<String> callback;Eval(String s,ValueCallback<String> c){script=s;callback=c;}}
 public List<Eval> evals=new ArrayList<>();public final int id;public boolean destroyed=false;public WebViewClient client;public String url;private WebSettings settings=new WebSettings();
 public WebView(android.content.Context c){super(c);id=instances.size();instances.add(this);settings.id=id;events.add(id+":new");}
 private void call(String action){if(destroyed)throw new AssertionError("Method after destroy: "+action);events.add(id+":"+action);}
 public static void setWebContentsDebuggingEnabled(boolean b){}public WebSettings getSettings(){return settings;}
 public void onResume(){call("onResume");}public void onPause(){call("onPause");}public void pauseTimers(){call("pauseTimers");}public void resumeTimers(){call("resumeTimers");}
 public void destroy(){call("destroy");destroyed=true;}public void stopLoading(){call("stopLoading");}public void removeJavascriptInterface(String n){call("removeBridge");}public void addJavascriptInterface(Object o,String n){call("addBridge");}
 public void setWebViewClient(WebViewClient c){client=c;}public void setWebChromeClient(WebChromeClient c){}
 public void loadUrl(String u){url=u;call("load");}public String getUrl(){return url;}
 public void evaluateJavascript(String s,ValueCallback<String> c){call("eval");evals.add(new Eval(s,c));if(evalResult!=null&&c!=null)c.onReceiveValue(evalResult);}
 public void clearHistory(){call("clearHistory");}public void clearCache(boolean b){call("clearCache");}public boolean canGoBack(){return false;}public void goBack(){}
}
