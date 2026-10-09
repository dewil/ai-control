package ru.dewil.aicontrol;

import android.app.*;
import android.os.*;
import android.content.*;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.net.Uri;
import android.net.http.SslError;
import android.view.*;
import android.view.inputmethod.InputMethodManager;
import android.webkit.*;
import android.widget.*;
import java.io.ByteArrayInputStream;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;
import org.json.JSONObject;
import org.json.JSONTokener;
import ru.dewil.aicontrol.policy.*;

/** Fixed-origin shell. Capabilities never cross the JavaScript bridge. */
public final class MainActivity extends androidx.activity.ComponentActivity {
    private final Handler ui=new Handler(Looper.getMainLooper());
    private final ExecutorService io=Executors.newSingleThreadExecutor();
    private final AuthGate gate=new AuthGate();
    private CredentialStore store;
    private volatile CredentialStore.Record credential;
    private FrameLayout root;
    private LinearLayout overlay;
    private TextView status;
    private Button retry;
    private volatile WebView web;
    private EditText username,password,totp;
    private String nativeCookie;
    private long epoch=0,pageEpoch=0,authGeneration=0;
    private boolean imeVisible=false,clearPending=false,storageBroken=false;
    private volatile boolean foreground=false;
    private boolean loading=false,pageLoaded=false,loginVisible=false,mainFrameFailed=false;
    private enum Dispatch { BLOCKED, BOOTSTRAP, ADMITTING, ACTIVE }
    private volatile Dispatch dispatch=Dispatch.BLOCKED;
    private long lifecycleGeneration=0,navigationGeneration=0,commandSerial=0,commandGeneration=0;
    private boolean backgroundSuspended=false,timersPaused=false,unsupportedWeb=false,blockedUnconfirmed=false,cookieAccepted=false;
    private long suspendDeadline=0;
    private Runnable commandDeadline,commandPoll;
    private static final long MAX_SERIAL=9007199254740991L;
    private final Runnable renewal=()->admit(false);
    private final Runnable banner=new Runnable(){public void run(){if(!foreground)return;View view=root.findViewWithTag("updates");if(view instanceof Button){ru.dewil.aicontrol.updater.UpdateInfo available=((ru.dewil.aicontrol.updater.UpdateRepositoryOwner)getApplication()).getUpdateRepository().getState().getValue().getAvailable();((Button)view).setText(available==null?"Обновления":"Доступно обновление "+available.getVersionName());}ui.postDelayed(this,5000);}};

    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);
        getWindow().setStatusBarColor(0xff141414);getWindow().setNavigationBarColor(0xff141414);
        getOnBackPressedDispatcher().addCallback(this,new androidx.activity.OnBackPressedCallback(true){@Override public void handleOnBackPressed(){handleBack();}});
        store=new CredentialStore(this);
        root=new FrameLayout(this);root.setBackgroundColor(0xff141414);setContentView(root);
        // PhoneWindow requires an initialized DecorView before querying its controller.
        if(Build.VERSION.SDK_INT>=30){WindowInsetsController bars=getWindow().getInsetsController();if(bars!=null)bars.setSystemBarsAppearance(0,WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS|WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS);}
        root.setOnApplyWindowInsetsListener((view,insets)->{
            if(Build.VERSION.SDK_INT>=30){imeVisible=insets.isVisible(WindowInsets.Type.ime());android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.ime());
                view.setPadding(bars.left,bars.top,bars.right,bars.bottom);
            }else view.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());return insets;
        });
        try{credential=store.load();}catch(Exception e){credential=null;storageBroken=true;showFailure("Не удалось прочитать сохраненный вход. Очистите данные приложения и войдите снова.",false);return;}
        if(credential==null)showLogin();else showWait("Восстанавливаем вход…");
    }
    @Override public void onStart(){super.onStart();((ru.dewil.aicontrol.updater.UpdateRepositoryOwner)getApplication()).getUpdateRepository().onAppResumed();}
    @Override protected void onResume(){super.onResume();foreground=true;epoch++;lifecycleGeneration++;cancelPageCommand();suspendDeadline=0;backgroundSuspended=false;cookieAccepted=false;
        authGeneration=gate.begin();
        if(unsupportedWeb||blockedUnconfirmed){blockedMessage();return;}
        ui.removeCallbacks(banner);ui.post(banner);
        if(credential!=null){if("PENDING_LOGOUT".equals(credential.state))revoke();else admit(true);}
        else if(!storageBroken){if(clearPending)showWait("Удаляем веб-сессию…");else if(!loginVisible)showLogin();}
    }
    @Override protected void onPause(){pausePanel();super.onPause();}
    private void pausePanel(){
        foreground=false;dispatch=Dispatch.BLOCKED;
        if(web!=null)web.getSettings().setBlockNetworkLoads(true);
        ui.removeCallbacks(renewal);ui.removeCallbacks(banner);
        if(backgroundSuspended)return;
        backgroundSuspended=true;epoch++;lifecycleGeneration++;loading=false;gate.stop();cancelPageCommand();
        if(web!=null&&!unsupportedWeb&&!blockedUnconfirmed)suspendPage(null,false);
    }
    @Override public void onStop(){pausePanel();super.onStop();}
    @Override public void onDestroy(){foreground=false;epoch++;lifecycleGeneration++;cancelPageCommand();ui.removeCallbacks(renewal);ui.removeCallbacks(banner);io.shutdownNow();disposeWeb();super.onDestroy();}
    private boolean current(long version){return foreground&&!isFinishing()&&epoch==version;}
    private boolean authCurrent(long version,long generation,WebView owner,long navigation,long life){return active(version,generation)&&web==owner&&navigationGeneration==navigation&&lifecycleGeneration==life;}
    private boolean active(long version,long generation){return current(version)&&credential!=null&&"ACTIVE".equals(credential.state)&&gate.canApply(generation);}
    private LinearLayout box(boolean login){
        loginVisible=false;
        if(password!=null)password.setText("");if(totp!=null)totp.setText("");
        if(overlay!=null)root.removeView(overlay);
        overlay=new LinearLayout(this);overlay.setOrientation(LinearLayout.VERTICAL);overlay.setGravity(Gravity.CENTER);
        overlay.setPadding(32,32,32,32);overlay.setBackgroundColor(0xff141414);overlay.setClickable(true);
        root.addView(overlay,new FrameLayout.LayoutParams(-1,-1));
        if(!login)overlay.addView(updatesEntry());
        status=new TextView(this);status.setTextSize(18);overlay.addView(status);return overlay;
    }
    private Button updatesEntry(){Button updates=new Button(this);updates.setText("Обновления приложения");updates.setOnClickListener(v->startActivity(new Intent(this,UpdatesActivity.class)));return updates;}
    private void showWait(String message){box(false);status.setText(message);}
    private void showFailure(String message,boolean canRetry){showWait(message);if(canRetry){retry=new Button(this);retry.setText("Повторить");overlay.addView(retry);retry.setOnClickListener(v->{if(credential!=null&&"PENDING_LOGOUT".equals(credential.state))revoke();else admit(false);});}}
    private void showLogin(){
        box(true);status.setText("Вход в ai-control");
        username=new EditText(this);username.setHint("Логин");username.setInputType(1);username.setSaveEnabled(false);username.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);overlay.addView(username);
        password=new EditText(this);password.setHint("Пароль");password.setInputType(129);password.setSaveEnabled(false);password.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);overlay.addView(password);
        totp=new EditText(this);totp.setHint("Код TOTP");totp.setInputType(2);totp.setSaveEnabled(false);totp.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);overlay.addView(totp);
        Button login=new Button(this);login.setText("Войти");overlay.addView(login);login.setOnClickListener(v->login());
        float density=getResources().getDisplayMetrics().density;
        View gap=new View(this);overlay.addView(gap,new LinearLayout.LayoutParams(1,(int)(16*density)));
        Button updates=updatesEntry();updates.setTextSize(14);overlay.addView(updates,new LinearLayout.LayoutParams(-2,(int)(48*density)));
        loginVisible=true;
    }
    private void login(){
        if(!foreground||loading)return;
        final JSONObject body=new JSONObject();try{body.put("username",username.getText().toString());body.put("password",password.getText().toString());body.put("totp",totp.getText().toString());}catch(Exception e){return;}
        password.setText("");totp.setText("");loading=true;long version=++epoch;long generation=gate.resetAfterExplicitLogin();authGeneration=generation;showWait("Входим…");
        io.execute(()->{try{AuthHttp.Result result=AuthHttp.post("/api/app/login",null,null,body);
            ui.post(()->{if(!current(version)||!gate.canApply(generation))return;loading=false;
                if(result.status!=200){showLogin();status.setText("Не удалось войти. Проверьте логин, пароль и код.");return;}
                try{String token=result.body.getString("device_token");
                    if(result.cookie==null)throw new Exception();
                    store.save(token,"ACTIVE");credential=new CredentialStore.Record(token,"ACTIVE");installCookie(result,version,generation);
                }catch(Exception e){showFailure("Не удалось сохранить вход.",false);}
            });
        }catch(Exception e){ui.post(()->{if(current(version)){loading=false;showLogin();status.setText("Сервер недоступен. Повторите вход.");}});}});
    }
    private void admit(boolean opened){
        if(!foreground||loading||unsupportedWeb||blockedUnconfirmed||credential==null||!"ACTIVE".equals(credential.state)||!gate.canApply(authGeneration))return;
        loading=true;long version=++epoch;long generation=gate.begin();authGeneration=generation;String token=credential.token,cookie=nativeCookie;final WebView owner=web;final long navigation=navigationGeneration,life=lifecycleGeneration;
        cookieAccepted=false;dispatch=Dispatch.BLOCKED;if(web!=null)web.getSettings().setBlockNetworkLoads(true);showWait("Восстанавливаем вход…");
        io.execute(()->{try{JSONObject body=new JSONObject().put("foreground_open",opened);
            AuthHttp.Result result=AuthHttp.post("/api/app/session",token,cookie,body);
            ui.post(()->{if(!authCurrent(version,generation,owner,navigation,life))return;loading=false;
                if(AuthOutcome.INSTANCE.shouldClearToken(result.status,result.body.optString("error"))){terminal();return;}
                if(result.status!=200||!"ok".equals(result.body.optString("status"))||!(result.body.opt("session_replaced") instanceof Boolean)||result.cookie==null){if(web!=null)failedResume(false);else showFailure("Не удалось восстановить вход. Повторите подключение.",true);return;}
                installCookie(result,version,generation);
            });
        }catch(Exception e){ui.post(()->{if(authCurrent(version,generation,owner,navigation,life)){loading=false;if(web!=null)failedResume(false);else showFailure("Сервер недоступен. Сохраненный вход остается на устройстве.",true);}});}});
    }
    private void installCookie(AuthHttp.Result result,long version,long generation){
        if(!active(version,generation))return;
        final WebView owner=web;final long navigation=navigationGeneration,life=lifecycleGeneration;
        nativeCookie=result.cookie.split(";",2)[0];
        CookieManager cookies=CookieManager.getInstance();cookies.setAcceptCookie(true);
        cookies.setCookie(AuthHttp.ORIGIN,result.cookie,accepted->{
            if(!authCurrent(version,generation,owner,navigation,life))return;
            if(!accepted){if(web!=null)failedResume(false);else showFailure("Не удалось восстановить веб-сессию.",true);return;}
            cookies.flush();cookieAccepted=true;ensureWeb();
            if(timersPaused){web.resumeTimers();timersPaused=false;}web.onResume();web.getSettings().setBlockNetworkLoads(true);
            loading=true;pageEpoch=version;
            if(!pageLoaded){dispatch=Dispatch.BOOTSTRAP;web.getSettings().setBlockNetworkLoads(false);bootstrapDeadline();web.loadUrl(AuthHttp.ORIGIN+"/");}
            else suspendPage(()->resumePage(version,generation,"admit",0));
        });
    }
    private void cancelPageCommand(){commandGeneration++;if(commandDeadline!=null)ui.removeCallbacks(commandDeadline);if(commandPoll!=null)ui.removeCallbacks(commandPoll);commandDeadline=null;commandPoll=null;}
    private long nextSerial(){if(commandSerial>=MAX_SERIAL){unsupportedWeb=true;blockedMessage();return 0;}return ++commandSerial;}
    private void blockNetwork(){dispatch=Dispatch.BLOCKED;if(web!=null)web.getSettings().setBlockNetworkLoads(true);ui.removeCallbacks(renewal);}
    private void pauseTimers(){if(web!=null&&!timersPaused){web.onPause();web.pauseTimers();timersPaused=true;}}
    private void blockedMessage(){if(!foreground)return;showFailure(unsupportedWeb?
        "Обновите веб-панель на сервере, затем вручную перезапустите приложение. Несохранённый черновик будет потерян; сохранённый вход останется.":
        "Панель не отвечает. Вручную перезапустите приложение. Несохранённый черновик будет потерян; сохранённый вход останется.",false);}
    private void pausedMessage(){if(!foreground)return;if(unsupportedWeb||blockedUnconfirmed)blockedMessage();else showFailure("Не удалось восстановить панель. Повторите подключение.",true);}
    private JSONObject decoded(String value){try{Object text=new JSONTokener(value).nextValue();return text instanceof String?new JSONObject((String)text):null;}catch(Exception e){return null;}}
    private boolean commandCurrent(WebView owner,long operation,long life,long navigation,long auth){return owner==web&&operation==commandGeneration&&life==lifecycleGeneration&&navigation==navigationGeneration&&auth==authGeneration&&!isFinishing();}
    private boolean suspendAck(JSONObject value,long serial){return value!=null&&value.length()==4&&value.opt("protocol") instanceof Number&&value.optDouble("protocol")==2&&"suspend".equals(value.opt("action"))&&value.opt("serial") instanceof Number&&value.optDouble("serial")==serial&&Boolean.TRUE.equals(value.opt("ok"));}
    private void suspendPage(Runnable admitted){suspendPage(admitted,true);}
    private void suspendPage(Runnable admitted,boolean terminalTimeout){
        blockNetwork();cancelPageCommand();final WebView owner=web;if(owner==null)return;
        final long serial=nextSerial(),operation=commandGeneration,life=lifecycleGeneration,navigation=navigationGeneration,auth=authGeneration;
        if(serial==0)return;final long deadline=SystemClock.elapsedRealtime()+500;suspendDeadline=deadline;final boolean loaded=pageLoaded;
        commandDeadline=()->{if(!commandCurrent(owner,operation,life,navigation,auth))return;cancelPageCommand();blockedUnconfirmed=terminalTimeout&&loaded&&!unsupportedWeb;loading=false;pauseTimers();pausedMessage();};
        ui.postDelayed(commandDeadline,Math.max(0,deadline-SystemClock.elapsedRealtime()));
        if(!loaded){mainFrameFailed=true;owner.stopLoading();return;}
        String script="(function(){try{const p={protocol:2,serial:"+serial+"};let supported=false;try{supported=typeof window.aiControlAndroidLifecycleProtocol==='function'&&window.aiControlAndroidLifecycleProtocol()===2;}catch(_){}const fn=window.aiControlAndroidSuspend;if(typeof fn!=='function')return JSON.stringify({unsupported:true});const ack=fn(p);return JSON.stringify(supported?ack:{unsupported:true});}catch(_){return JSON.stringify({unsupported:true});}})()";
        owner.evaluateJavascript(script,value->{
            if(!commandCurrent(owner,operation,life,navigation,auth)||SystemClock.elapsedRealtime()>=deadline)return;
            JSONObject result=decoded(value);
            if(suspendAck(result,serial)){suspendDeadline=0;cancelPageCommand();if(admitted!=null&&foreground&&!unsupportedWeb&&!blockedUnconfirmed)admitted.run();else{pauseTimers();loading=false;pausedMessage();}}
            else if(result==null||Boolean.TRUE.equals(result.opt("unsupported"))){unsupportedWeb=true;blockNetwork();blockedMessage();}
        });
    }
    private void navigationPause(long deadline){
        if(timersPaused||deadline==0)return;final WebView owner=web;final long operation=commandGeneration,life=lifecycleGeneration,navigation=navigationGeneration,auth=authGeneration;
        commandDeadline=()->{if(!commandCurrent(owner,operation,life,navigation,auth))return;cancelPageCommand();loading=false;pauseTimers();pausedMessage();};
        ui.postDelayed(commandDeadline,Math.max(0,deadline-SystemClock.elapsedRealtime()));
    }
    private void bootstrapDeadline(){
        cancelPageCommand();final WebView owner=web;final long operation=commandGeneration,life=lifecycleGeneration,navigation=navigationGeneration,auth=authGeneration;
        commandDeadline=()->{if(commandCurrent(owner,operation,life,navigation,auth)){loading=false;suspendPage(null);}};ui.postDelayed(commandDeadline,10000);
    }
    private void failedResume(boolean unsupported){blockNetwork();cancelPageCommand();unsupportedWeb|=unsupported;if(timersPaused){loading=false;pausedMessage();return;}suspendPage(null);}
    private void resumePage(long version,long generation,String phase,long admissionSerial){
        if(!active(version,generation)||web==null)return;cancelPageCommand();final WebView owner=web;
        final long serial=nextSerial(),operation=commandGeneration,life=lifecycleGeneration,navigation=navigationGeneration,auth=authGeneration;
        if(serial==0)return;final long deadline=SystemClock.elapsedRealtime()+("admit".equals(phase)?10000:500);
        if("admit".equals(phase)){dispatch=Dispatch.ADMITTING;owner.getSettings().setBlockNetworkLoads(false);}
        commandDeadline=()->{if(commandCurrent(owner,operation,life,navigation,auth))failedResume(false);};ui.postDelayed(commandDeadline,Math.max(0,deadline-SystemClock.elapsedRealtime()));
        String args="{protocol:2,serial:"+serial+",phase:'"+phase+"'"+("activate".equals(phase)?",admissionSerial:"+admissionSerial:"")+"}";
        String script="(function(){try{if(typeof window.aiControlAndroidLifecycleProtocol!=='function'||window.aiControlAndroidLifecycleProtocol()!==2||typeof window.aiControlAndroidResume!=='function')return JSON.stringify({unsupported:true});const p="+args+";const slot={serial:p.serial,phase:p.phase,ok:null};window.aiControlAndroidResumeResult=slot;Promise.resolve(window.aiControlAndroidResume(p)).then(ok=>{if(window.aiControlAndroidResumeResult===slot)slot.ok=ok===true;},()=>{if(window.aiControlAndroidResumeResult===slot)slot.ok=false;});return JSON.stringify({started:true});}catch(_){return JSON.stringify({unsupported:true});}})()";
        owner.evaluateJavascript(script,value->{if(!commandCurrent(owner,operation,life,navigation,auth)||SystemClock.elapsedRealtime()>=deadline)return;JSONObject result=decoded(value);if(result==null||!Boolean.TRUE.equals(result.opt("started"))){failedResume(true);return;}awaitResume(owner,operation,life,navigation,auth,version,generation,serial,phase,deadline);});
    }
    private void awaitResume(WebView owner,long operation,long life,long navigation,long auth,long version,long generation,long serial,String phase,long deadline){
        if(!commandCurrent(owner,operation,life,navigation,auth)||!active(version,generation)||SystemClock.elapsedRealtime()>=deadline)return;
        commandPoll=()->{if(!commandCurrent(owner,operation,life,navigation,auth)||SystemClock.elapsedRealtime()>=deadline)return;
            owner.evaluateJavascript("(function(){try{if(typeof window.aiControlAndroidLifecycleProtocol!=='function'||window.aiControlAndroidLifecycleProtocol()!==2||typeof window.aiControlAndroidResume!=='function')return JSON.stringify({unsupported:true});return JSON.stringify(window.aiControlAndroidResumeResult);}catch(_){return JSON.stringify({unsupported:true});}})()",value->{
                if(!commandCurrent(owner,operation,life,navigation,auth)||!active(version,generation)||SystemClock.elapsedRealtime()>=deadline)return;
                JSONObject result=decoded(value);
                if(result==null||Boolean.TRUE.equals(result.opt("unsupported"))){failedResume(true);return;}
                if(result.length()!=3||!(result.opt("serial") instanceof Number)||result.optDouble("serial")!=serial||!phase.equals(result.opt("phase"))){failedResume(false);return;}
                Object ok=result.opt("ok");if(Boolean.TRUE.equals(ok)){cancelPageCommand();if("admit".equals(phase)){dispatch=Dispatch.ACTIVE;resumePage(version,generation,"activate",serial);}else{loading=false;hideOverlay();ui.removeCallbacks(renewal);ui.postDelayed(renewal,2*60*60*1000L);}}
                else if(Boolean.FALSE.equals(ok)||ok!=JSONObject.NULL)failedResume(false);
                else awaitResume(owner,operation,life,navigation,auth,version,generation,serial,phase,deadline);
            });};ui.postDelayed(commandPoll,100);
    }
    private boolean shellUrl(String url){try{return OriginPolicy.INSTANCE.classify(url,true,false,"GET",false)==NavigationDecision.ALLOW_PANEL&&"/".equals(java.net.URI.create(url).getRawPath());}catch(Exception error){return false;}}
    private boolean panelRequestAllowed(WebResourceRequest request){
        if(dispatch==Dispatch.ACTIVE)return true;
        if(!"GET".equals(request.getMethod()))return false;
        try{java.net.URI uri=java.net.URI.create(request.getUrl().toString());String path=uri.getRawPath();
            if(dispatch==Dispatch.ADMITTING)return "/api/session".equals(path)&&uri.getRawQuery()==null;
            if(dispatch!=Dispatch.BOOTSTRAP)return false;
            return ("/".equals(path)||"/web.js".equals(path)||"/web.css".equals(path)||"/devbus.js".equals(path)||"/devbus.css".equals(path)||"/favicon.svg".equals(path)||"/favicon.ico".equals(path))&&("/".equals(path)||uri.getRawQuery()==null);
        }catch(Exception e){return false;}
    }
    private void disposeWeb(){
        blockNetwork();navigationGeneration++;cancelPageCommand();WebView page=web;
        unsupportedWeb=false;blockedUnconfirmed=false;cookieAccepted=false;mainFrameFailed=false;
        if(page==null)return;WebView receiver=timersPaused?new WebView(this):null;
        root.removeView(page);page.stopLoading();page.removeJavascriptInterface("AndroidAuth");page.destroy();web=null;
        if(receiver!=null){receiver.resumeTimers();timersPaused=false;receiver.destroy();}
    }
    private void hideOverlay(){if(overlay!=null){root.removeView(overlay);overlay=null;}}
    private final class Bridge {
        private final WebView owner;Bridge(WebView owner){this.owner=owner;}
        @JavascriptInterface public void requestAuth(){ui.post(()->{if(owner==web&&foreground&&dispatch==Dispatch.ACTIVE)admit(false);});}
        @JavascriptInterface public void requestLogout(){ui.post(()->{if(owner==web&&dispatch==Dispatch.ACTIVE)logout();});}
    }
    private void ensureWeb(){if(web!=null)return;
        web=new WebView(this);navigationGeneration++;cancelPageCommand();WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        WebSettings settings=web.getSettings();settings.setJavaScriptEnabled(true);settings.setDomStorageEnabled(true);settings.setUserAgentString(settings.getUserAgentString()+" AiControlLifecycle/2");settings.setBlockNetworkLoads(true);
        settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSafeBrowsingEnabled(true);settings.setSupportMultipleWindows(false);settings.setJavaScriptCanOpenWindowsAutomatically(false);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web,false);
        web.addJavascriptInterface(new Bridge(web),"AndroidAuth");
        final WebView instance=web;
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){
                if(view!=instance||!foreground||credential==null||!"ACTIVE".equals(credential.state)||dispatch!=Dispatch.ACTIVE&&!panelRequestAllowed(request))return true;
                NavigationDecision decision=OriginPolicy.INSTANCE.classify(request.getUrl().toString(),request.isForMainFrame(),request.hasGesture(),request.getMethod(),request.isRedirect());
                if(decision==NavigationDecision.OPEN_BROWSER){try{startActivity(new Intent(Intent.ACTION_VIEW,request.getUrl()).addCategory(Intent.CATEGORY_BROWSABLE));}catch(ActivityNotFoundException ignored){new AlertDialog.Builder(MainActivity.this).setMessage("Не найден браузер для открытия ссылки.").setPositiveButton("Закрыть",null).show();}return true;}
                return decision!=NavigationDecision.ALLOW_PANEL;
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest request){
                if(view!=instance||view!=web||!foreground||credential==null||!"ACTIVE".equals(credential.state)||!panelRequestAllowed(request)||OriginPolicy.INSTANCE.classify(request.getUrl().toString(),request.isForMainFrame(),false,request.getMethod(),request.isRedirect())!=NavigationDecision.ALLOW_PANEL)
                    return new WebResourceResponse("text/plain","UTF-8",403,"Blocked",java.util.Collections.emptyMap(),new ByteArrayInputStream(new byte[0]));
                return null;
            }
            private boolean viewCurrent(){return web==instance;}
            private void failedPage(){if(viewCurrent()&&foreground&&!unsupportedWeb&&!blockedUnconfirmed&&pageEpoch==epoch){mainFrameFailed=true;pageLoaded=false;loading=false;failedResume(false);}}
            @Override public void onReceivedError(WebView view,WebResourceRequest request,WebResourceError error){if(request.isForMainFrame())failedPage();}
            @Override public void onReceivedHttpError(WebView view,WebResourceRequest request,WebResourceResponse response){if(request.isForMainFrame())failedPage();}
            @Override public void onReceivedSslError(WebView view,SslErrorHandler handler,SslError error){handler.cancel();if(view==instance&&view==web&&error.getUrl()!=null&&error.getUrl().equals(view.getUrl()))failedPage();}
            @Override public void onPageFinished(WebView view,String url){if(view!=instance||!viewCurrent()||mainFrameFailed||!shellUrl(url)||!url.equals(view.getUrl()))return;pageLoaded=true;if(foreground&&!unsupportedWeb&&!blockedUnconfirmed&&cookieAccepted&&pageEpoch==epoch&&dispatch==Dispatch.BOOTSTRAP&&loading){cancelPageCommand();suspendPage(()->resumePage(pageEpoch,authGeneration,"admit",0));}}
            @Override public boolean onRenderProcessGone(WebView view,RenderProcessGoneDetail detail){if(!viewCurrent())return true;navigationGeneration++;cancelPageCommand();destroyPage();loading=false;showFailure("Панель закрылась; несохранённый черновик потерян. Повторите подключение.",true);return true;}
            @Override public void onPageStarted(WebView view,String url,android.graphics.Bitmap icon){
                if(view!=instance||!viewCurrent())return;mainFrameFailed=false;long deadline=suspendDeadline;navigationGeneration++;cancelPageCommand();
                if(!foreground||unsupportedWeb||blockedUnconfirmed){blockNetwork();navigationPause(deadline);return;}
                if(!cookieAccepted||credential==null||!"ACTIVE".equals(credential.state)){blockNetwork();loading=false;return;}
                dispatch=Dispatch.BOOTSTRAP;loading=true;pageLoaded=false;pageEpoch=epoch;bootstrapDeadline();
                if(!shellUrl(url)){mainFrameFailed=true;pageLoaded=false;loading=false;blockNetwork();view.stopLoading();showFailure("Переход заблокирован.",true);}
            }
        });
        int footerHeight=(int)(48*getResources().getDisplayMetrics().density);
        web.setWebChromeClient(new WebChromeClient());FrameLayout.LayoutParams layout=new FrameLayout.LayoutParams(-1,-1);layout.bottomMargin=footerHeight;root.addView(web,0,layout);
        Button updates=new Button(this);updates.setText("Обновления");updates.setTextSize(14);
        updates.setBackgroundTintList(new ColorStateList(new int[][]{{android.R.attr.state_enabled,android.R.attr.state_pressed},{android.R.attr.state_enabled,android.R.attr.state_focused},{-android.R.attr.state_enabled},{}},new int[]{0xff3a3a3a,0xff3a3a3a,0xff242424,0xff141414}));
        updates.setFocusable(true);updates.setOnClickListener(v->startActivity(new Intent(this,UpdatesActivity.class)));updates.setTag("updates");FrameLayout.LayoutParams bar=new FrameLayout.LayoutParams(-2,footerHeight,Gravity.BOTTOM|Gravity.END);root.addView(updates,1,bar);
    }
    private void destroyPage(){View bar=root.findViewWithTag("updates");if(bar!=null)root.removeView(bar);nativeCookie=null;pageLoaded=false;disposeWeb();WebStorage.getInstance().deleteAllData();}
    private void terminal(){epoch++;gate.deny();destroyPage();
        try{store.clear();credential=null;}catch(Exception e){storageBroken=true;showFailure("Не удалось удалить сохраненный вход. Очистите данные приложения.",false);}
        clearPending=true;CookieManager.getInstance().removeAllCookies(ok->{clearPending=false;CookieManager.getInstance().flush();if(foreground&&credential==null&&!storageBroken)showLogin();});
    }
    private void logout(){if(!foreground||credential==null||!"ACTIVE".equals(credential.state))return;
        epoch++;loading=false;gate.logout();ui.removeCallbacks(renewal);if(web!=null)web.getSettings().setBlockNetworkLoads(true);
        try{store.save(credential.token,"PENDING_LOGOUT");credential=new CredentialStore.Record(credential.token,"PENDING_LOGOUT");revoke();}
        catch(Exception e){
            destroyPage();clearPending=true;
            CookieManager.getInstance().removeAllCookies(ok->{clearPending=false;CookieManager.getInstance().flush();});
            showFailure("Не удалось сохранить выход. Выход на сервере не подтвержден. Повторите выход или очистите данные приложения.",false);
            Button retryLogout=new Button(this);retryLogout.setText("Повторить выход");overlay.addView(retryLogout);retryLogout.setOnClickListener(v->logout());
        }
    }
    private void revoke(){if(!foreground||loading||credential==null||!"PENDING_LOGOUT".equals(credential.state))return;
        loading=true;long version=++epoch;String token=credential.token;showWait("Завершаем вход на сервере…");
        io.execute(()->{try{AuthHttp.Result result=AuthHttp.post("/api/app/logout",token,null,new JSONObject());
            ui.post(()->{if(!current(version)||credential==null||!"PENDING_LOGOUT".equals(credential.state))return;loading=false;
                if((result.status==200&&"ok".equals(result.body.optString("status")))||AuthOutcome.INSTANCE.shouldClearToken(result.status,result.body.optString("error")))terminal();
                else showFailure("Выход ожидает подтверждения сервера. Повторите подключение.",true);
            });
        }catch(Exception e){ui.post(()->{if(current(version)){loading=false;showFailure("Сервер недоступен. Выход будет завершен при подключении.",true);}});}});
    }
    private void handleBack(){
        View focus=getCurrentFocus();if(focus!=null){InputMethodManager ime=(InputMethodManager)getSystemService(INPUT_METHOD_SERVICE);if(imeVisible||(Build.VERSION.SDK_INT<30&&ime.isAcceptingText())){ime.hideSoftInputFromWindow(focus.getWindowToken(),0);focus.clearFocus();return;}}
        if(overlay==null&&web!=null&&web.canGoBack()){web.goBack();return;}moveTaskToBack(true);
    }
}
