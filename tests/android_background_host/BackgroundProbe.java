package ru.dewil.aicontrol;
import android.webkit.*;
import android.os.Handler;
import android.view.*;
import android.widget.*;
import java.lang.reflect.*;
import java.util.*;
/** Public Activity callbacks + synthetic login, never implementation field inspection. */
public final class BackgroundProbe {
 static void check(boolean v,String message){if(!v)throw new AssertionError(message+" | events="+WebView.events);}
 static List<View> flatten(View v){List<View> all=new ArrayList<>();all.add(v);if(v instanceof ViewGroup){ViewGroup g=(ViewGroup)v;for(int i=0;i<g.getChildCount();i++)all.addAll(flatten(g.getChildAt(i)));}return all;}
 static void lifecycle(MainActivity a,String name)throws Exception{Class<?> type=MainActivity.class;while(type!=null){try{Method method=type.getDeclaredMethod(name);method.setAccessible(true);method.invoke(a);return;}catch(NoSuchMethodException missing){type=type.getSuperclass();}}throw new AssertionError("Missing Activity callback "+name);}
 static MainActivity login()throws Exception {
  MainActivity a=new MainActivity();a.onCreate(null);a.onStart();
  // Invoke the real Android callback regardless of public/protected override visibility.
  lifecycle(a,"onResume");
  for(View v:flatten(a.getWindow().getDecorView()))if(v instanceof EditText){EditText e=(EditText)v;e.setText("Код TOTP".contentEquals(e.getHint())?"123456":"synthetic-only");}
  for(View v:flatten(a.getWindow().getDecorView()))if(v instanceof Button&&"Войти".contentEquals(((Button)v).getText()))v.performClick();
  long deadline=System.nanoTime()+2_000_000_000L;
  while(WebView.instances.isEmpty()&&System.nanoTime()<deadline){Handler.runPosted();Thread.sleep(2);}
  Handler.runPosted();check(!WebView.instances.isEmpty(),"Synthetic native login did not create WebView");return a;
 }
 static MainActivity login(boolean loaded)throws Exception{MainActivity activity=login();if(loaded)finishPage(activity);return activity;}
 static WebView.Eval latest(WebView page){check(!page.evals.isEmpty(),"Expected native lifecycle evaluation");return page.evals.get(page.evals.size()-1);}
 static String result(org.json.JSONObject value){return org.json.JSONObject.quote(value.toString());}
 static void completeResume(WebView page,String phase)throws Exception{
  WebView.Eval command=latest(page);long commandSerial=serial(command);
  check(command.script.contains("aiControlAndroidResume"),"Loaded fixture expected Resume command");
  command.callback.onReceiveValue(result(new org.json.JSONObject().put("started",true)));
  Handler.advance(100);WebView.Eval poll=latest(page);check(poll!=command,"Loaded fixture expected bounded result polling");
  poll.callback.onReceiveValue(result(new org.json.JSONObject().put("serial",commandSerial).put("phase",phase).put("ok",true)));Handler.runPosted();
 }
 static void finishPage(MainActivity activity)throws Exception{
  WebView page=page();check(page.client!=null,"Loaded fixture requires WebView client");page.client.onPageFinished(page,page.url);
  WebView.Eval preflight=latest(page);check(preflight.script.contains("aiControlAndroidSuspend"),"Loaded fixture requires structured protocol/preflight");
  preflight.callback.onReceiveValue(ack(serial(preflight)));completeResume(page,"admit");completeResume(page,"activate");
  check(page.client.shouldInterceptRequest(page,request("/api/session-send","POST"))==null,"Loaded fixture did not reach native ACTIVE");
 }
 static WebView page(){return WebView.instances.get(0);}
 static int count(String action){int n=0;for(String s:WebView.events)if(s.equals(page().id+":"+action))n++;return n;}
 static void pause(MainActivity a)throws Exception{lifecycle(a,"onPause");}
 static long serial(WebView.Eval eval){
  java.util.regex.Matcher m=java.util.regex.Pattern.compile("[\\\"']?serial[\\\"']?\\s*[:=]\\s*(\\d+)").matcher(eval.script.replace("\\\"","\""));
  check(m.find(),"Suspend command does not contain public serial: "+eval.script);return Long.parseLong(m.group(1));
 }
 static String ack(long serial)throws Exception{return org.json.JSONObject.quote(new org.json.JSONObject().put("protocol",2).put("action","suspend").put("serial",serial).put("ok",true).toString());}
 static WebResourceRequest request(String path,String method){return new WebResourceRequest(){public android.net.Uri getUrl(){java.net.URI origin=java.net.URI.create(page().url);return android.net.Uri.parse(origin.getScheme()+"://"+origin.getRawAuthority()+path);}public boolean isForMainFrame(){return path.startsWith("/")&&path.length()<2;}public boolean isRedirect(){return false;}public boolean hasGesture(){return false;}public String getMethod(){return method;}public Map<String,String> getRequestHeaders(){return Collections.emptyMap();}};}
 public static void main(String[] args){try{run(args);System.out.println("PASS host "+args[0]);System.exit(0);}catch(Throwable e){e.printStackTrace();System.exit(1);}}
 public static void run(String[] args)throws Exception {
  String test=args[0];boolean loaded=!(test.equals("ua")||test.equals("login")||test.equals("bootstrap")||test.equals("bootstrap-stop")||test.startsWith("protocol"));
  MainActivity a=login(loaded);WebView p=page();WebView.events.clear();p.evals.clear();
  if(test.equals("ua")){check(p.getSettings().getUserAgentString().contains("AiControlLifecycle/2"),"INV-BATT-04: missing UA protocol marker");return;}
  if(test.equals("bootstrap")){
   check(p.client!=null,"Missing native interceptor");
   for(String path:new String[]{"/","/?project=demo","/web.js","/web.css","/devbus.js","/devbus.css","/favicon.svg","/favicon.ico"})check(p.client.shouldInterceptRequest(p,request(path,"GET"))==null,"INV-BATT-10: BOOTSTRAP denied exact allowed GET "+path);
   for(String path:new String[]{"/api/session","/api/tasks","/api/session-send","/another.js","/web.js?revision=1","/favicon.ico?x=1","/web.js/child"})check(p.client.shouldInterceptRequest(p,request(path,"GET"))!=null,"INV-BATT-10: BOOTSTRAP admitted forbidden GET "+path);
   for(String path:new String[]{"/","/web.js","/devbus.css","/favicon.svg"})check(p.client.shouldInterceptRequest(p,request(path,"POST"))!=null,"BOOTSTRAP admitted POST "+path);
   return;
  }
  if(test.startsWith("protocol")){
   WebView.evalResult=test.equals("protocolstring")?"\"2\"":test.equals("protocolother")?"3":test.equals("protocolobject")?"{}":"null";
   check(p.client!=null,"Missing WebView client");p.client.onPageFinished(p,p.url);Handler.runPosted();Handler.advance(500);
   check(p.getSettings().blocked,"INV-BATT-04: missing v2 protocol must block native loads; legacy fallback forbidden");
   check(!p.destroyed&&count("load")==0&&count("clearCache")==0,"Missing protocol discarded retained RAM page");
   check(count("pauseTimers")==1,"Missing protocol did not reach bounded paused outcome");
   for(WebView.Eval eval:p.evals)check(!java.util.regex.Pattern.compile("aiControlAndroidResume\\s*\\(\\s*\\)").matcher(eval.script).find(),"Unsupported protocol used forbidden legacy no-arg Resume");
   StringBuilder all=new StringBuilder();for(View v:flatten(a.getWindow().getDecorView()))if(v instanceof TextView)all.append(((TextView)v).getText()).append(' ');
   String text=all.toString().toLowerCase(java.util.Locale.ROOT);check(text.contains("обнов")&&text.contains("панел"),"Missing protocol needs actionable web update error");
   check(text.contains("перезапуст")&&text.contains("черновик")&&text.contains("вход"),"Unsupported overlay must explain manual restart/RAM loss/saved login");
   int evaluations=p.evals.size(),admissions=AuthHttp.calls;a.onStop();a.onStart();lifecycle(a,"onResume");Handler.advance(65000);
   check(p.evals.size()==evaluations&&AuthHttp.calls==admissions,"Unsupported web restarted JS/native admission automatically on foreground return");return;
  }
  if(test.equals("login")){
   MainActivity b=new MainActivity();b.onCreate(null);b.onStart();lifecycle(b,"onResume");EditText target=null;
   for(View v:flatten(b.getWindow().getDecorView()))if(v instanceof EditText&&"Пароль".contentEquals(((EditText)v).getHint()))target=(EditText)v;
   check(target!=null,"Login input missing");target.setText("retained synthetic password");target.requestFocus();target.setSelection(2,7);
   lifecycle(b,"onPause");b.onStop();b.onStart();lifecycle(b,"onResume");
   check(target.hasFocus()&&target.getSelectionStart()==2&&target.getSelectionEnd()==7&&"retained synthetic password".contentEquals(target.getText()),"INV-BATT-07: Home replaced login focus/text");return;
  }
  pause(a);
  if(test.equals("bootstrap-stop")){
   check(p.getSettings().blocked,"Unfinished BOOTSTRAP onPause did not block network");
   check(p.evals.isEmpty(),"Unfinished BOOTSTRAP must not execute missing page JS");
   check(count("stopLoading")==1,"Unfinished shell load was not stopped");
   Handler.advance(499);check(count("pauseTimers")==0,"Unfinished shell paused before bounded deadline");Handler.advance(1);check(count("pauseTimers")==1,"Unfinished shell missing bounded native pause");
   int admissions=AuthHttp.calls;a.onStop();a.onStart();lifecycle(a,"onResume");long until=System.nanoTime()+1_000_000_000L;
   while(AuthHttp.calls==admissions&&System.nanoTime()<until){Handler.runPosted();Thread.sleep(2);}Handler.runPosted();
   check(AuthHttp.calls>admissions,"Stopped initial shell was falsely latched unsupported instead of foreground admission");
   check(p.evals.isEmpty()&&!p.destroyed,"Initial shell recovery evaluated JS before page finish or discarded retained WebView");return;
  }
  if(test.equals("ack")||test.equals("wrongack")||test.equals("lateack")){
   check(p.evals.size()==1,"INV-BATT-01: missing one explicit suspend operation");WebView.Eval pending=p.evals.get(0);long serial=serial(pending);
   if(test.equals("lateack")){Handler.advance(500);check(count("pauseTimers")==1,"Missing deadline pause");pending.callback.onReceiveValue(ack(serial));check(count("pauseTimers")==1,"Late ACK duplicated timer pause");return;}
   pending.callback.onReceiveValue(test.equals("wrongack")?ack(serial+1):ack(serial));Handler.runPosted();
   if(test.equals("wrongack")){check(count("pauseTimers")==0,"Wrong serial accepted as suspend ACK");Handler.advance(500);check(count("pauseTimers")==1,"Malformed ACK suppressed independent deadline");}
   else{check(count("pauseTimers")==1&&count("onPause")==1,"INV-BATT-02/05: valid exact ACK did not pause once");Handler.advance(500);check(count("pauseTimers")==1,"ACK did not cancel deadline");}
   return;
  }
  if(test.equals("immediate")){
   check(p.getSettings().blocked,"INV-BATT-01: onPause did not immediately block panel loads");
   check(!p.evals.isEmpty(),"INV-BATT-01: onPause did not send explicit suspend while page visible");
   check(WebView.events.indexOf(p.id+":block:true")<WebView.events.indexOf(p.id+":eval"),"Block must precede JS evaluate");
   check(count("pauseTimers")==0&&count("onPause")==0,"INV-BATT-05: timer pause happened before async ACK/deadline");return;
  }
  if(test.equals("timeout")){
   check(count("pauseTimers")==0,"Pause before ACK deadline");Handler.advance(499);check(count("pauseTimers")==0,"500ms deadline fired early");Handler.advance(1);
   check(count("pauseTimers")==1&&count("onPause")==1,"INV-BATT-05: absent JS callback did not trigger bounded pause at500ms");
   check(!p.destroyed&&count("load")==0&&count("clearCache")==0,"INV-BATT-07: fallback destroyed or reloaded page");Handler.advance(65000);
   check(count("pauseTimers")==1,"Background retry loop after unconfirmed suspend");return;
  }
  if(test.equals("duplicate")){
   a.onStop();a.onStop();check(p.evals.size()==1,"INV-BATT-01/06: onStop did not coalesce same suspend");Handler.advance(500);
   check(count("pauseTimers")==1,"Duplicate global timer pause ownership");return;
  }
  if(test.equals("destroy")){
   Handler.advance(500);check(count("pauseTimers")==1,"Need timer ownership before destroy");a.onDestroy();
   check(p.destroyed,"Page WebView was not destroyed");int destroyed=WebView.events.indexOf(p.id+":destroy");
   check(!flatten(a.getWindow().getDecorView()).contains(p),"Destroyed page still attached to Activity root");
   check(WebView.events.indexOf(p.id+":removeBridge")>=0&&WebView.events.indexOf(p.id+":removeBridge")<destroyed,"Page bridge not removed before destroy");
   check(count("resumeTimers")==0,"INV-BATT-06: live/destroyed page used as global cleanup receiver");
   check(WebView.instances.size()==2,"Missing detached cleanup receiver");WebView receiver=WebView.instances.get(1);
   check(WebView.events.indexOf(receiver.id+":resumeTimers")>destroyed,"INV-BATT-06: global timers resumed before page destroy");
   check(receiver.destroyed&&receiver.evals.isEmpty()&&receiver.url==null,"Cleanup receiver loaded app content or was retained");return;
  }
  if(test.equals("return")){
   check(p.evals.size()==1,"No suspend to test stale return fence");a.onStop();a.onStart();lifecycle(a,"onResume");int paused=count("pauseTimers");Handler.advance(500);
   check(count("pauseTimers")==paused,"INV-BATT-06: stale stop deadline paused current return generation");return;
  }
  throw new AssertionError("Unknown host case");
 }
}
