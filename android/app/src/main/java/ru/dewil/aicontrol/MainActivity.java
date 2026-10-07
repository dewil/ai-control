package ru.dewil.aicontrol;

import android.app.*;
import android.os.*;
import android.content.*;
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
    private boolean loading=false,pageLoaded=false;
    private final Runnable renewal=()->admit(false);
    private final Runnable banner=new Runnable(){public void run(){if(!foreground)return;View view=root.findViewWithTag("updates");if(view instanceof Button){ru.dewil.aicontrol.updater.UpdateInfo available=((ru.dewil.aicontrol.updater.UpdateRepositoryOwner)getApplication()).getUpdateRepository().getState().getValue().getAvailable();((Button)view).setText(available==null?"Обновления":"Доступно обновление "+available.getVersionName());}ui.postDelayed(this,5000);}};

    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);
        getOnBackPressedDispatcher().addCallback(this,new androidx.activity.OnBackPressedCallback(true){@Override public void handleOnBackPressed(){handleBack();}});
        store=new CredentialStore(this);
        root=new FrameLayout(this);root.setBackgroundColor(Color.WHITE);setContentView(root);
        root.setOnApplyWindowInsetsListener((view,insets)->{
            if(Build.VERSION.SDK_INT>=30){imeVisible=insets.isVisible(WindowInsets.Type.ime());android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.ime());
                view.setPadding(bars.left,bars.top,bars.right,bars.bottom);
            }else view.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());return insets;
        });
        try{credential=store.load();}catch(Exception e){credential=null;storageBroken=true;showFailure("Не удалось прочитать сохраненный вход. Очистите данные приложения и войдите снова.",false);return;}
        if(credential==null)showLogin();else showWait("Восстанавливаем вход…");
    }
    @Override public void onStart(){super.onStart();foreground=true;((ru.dewil.aicontrol.updater.UpdateRepositoryOwner)getApplication()).getUpdateRepository().onAppResumed();ui.removeCallbacks(banner);ui.post(banner);epoch++;authGeneration=gate.begin();
        if(credential!=null){if("PENDING_LOGOUT".equals(credential.state))revoke();else admit(true);}
        if(web!=null)web.onResume();
        if(credential==null&&!storageBroken){if(clearPending)showWait("Удаляем веб-сессию…");else showLogin();}
    }
    @Override public void onStop(){foreground=false;epoch++;loading=false;gate.stop();ui.removeCallbacks(renewal);ui.removeCallbacks(banner);
        if(web!=null){web.getSettings().setBlockNetworkLoads(true);web.onPause();}super.onStop();}
    @Override public void onDestroy(){epoch++;io.shutdownNow();if(web!=null){root.removeView(web);web.destroy();web=null;}super.onDestroy();}
    private boolean current(long version){return foreground&&!isFinishing()&&epoch==version;}
    private boolean active(long version,long generation){return current(version)&&credential!=null&&"ACTIVE".equals(credential.state)&&gate.canApply(generation);}
    private LinearLayout box(){
        if(overlay!=null)root.removeView(overlay);
        overlay=new LinearLayout(this);overlay.setOrientation(LinearLayout.VERTICAL);overlay.setGravity(Gravity.CENTER);
        overlay.setPadding(32,32,32,32);overlay.setBackgroundColor(Color.WHITE);overlay.setClickable(true);
        root.addView(overlay,new FrameLayout.LayoutParams(-1,-1));
        Button updates=new Button(this);updates.setText("Обновления приложения");updates.setOnClickListener(v->startActivity(new Intent(this,UpdatesActivity.class)));overlay.addView(updates);
        status=new TextView(this);status.setTextSize(18);overlay.addView(status);return overlay;
    }
    private void showWait(String message){box();status.setText(message);}
    private void showFailure(String message,boolean canRetry){showWait(message);if(canRetry){retry=new Button(this);retry.setText("Повторить");overlay.addView(retry);retry.setOnClickListener(v->{if(credential!=null&&"PENDING_LOGOUT".equals(credential.state))revoke();else admit(false);});}}
    private void showLogin(){
        box();status.setText("Вход в ai-control");
        username=new EditText(this);username.setHint("Логин");username.setInputType(1);username.setSaveEnabled(false);username.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);overlay.addView(username);
        password=new EditText(this);password.setHint("Пароль");password.setInputType(129);password.setSaveEnabled(false);password.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);overlay.addView(password);
        totp=new EditText(this);totp.setHint("Код TOTP");totp.setInputType(2);totp.setSaveEnabled(false);totp.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);overlay.addView(totp);
        Button login=new Button(this);login.setText("Войти");overlay.addView(login);login.setOnClickListener(v->login());
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
        if(!foreground||loading||credential==null||!"ACTIVE".equals(credential.state))return;
        loading=true;long version=++epoch;long generation=gate.begin();authGeneration=generation;String token=credential.token,cookie=nativeCookie;
        if(web!=null)web.getSettings().setBlockNetworkLoads(true);showWait("Восстанавливаем вход…");
        io.execute(()->{try{JSONObject body=new JSONObject().put("foreground_open",opened);
            AuthHttp.Result result=AuthHttp.post("/api/app/session",token,cookie,body);
            ui.post(()->{if(!active(version,generation))return;loading=false;
                if(AuthOutcome.INSTANCE.shouldClearToken(result.status,result.body.optString("error"))){terminal();return;}
                if(result.status!=200||!"ok".equals(result.body.optString("status"))||!(result.body.opt("session_replaced") instanceof Boolean)||result.cookie==null){showFailure("Не удалось восстановить вход. Повторите подключение.",true);return;}
                installCookie(result,version,generation);
            });
        }catch(Exception e){ui.post(()->{if(active(version,generation)){loading=false;showFailure("Сервер недоступен. Сохраненный вход остается на устройстве.",true);}});}});
    }
    private void installCookie(AuthHttp.Result result,long version,long generation){
        if(!active(version,generation))return;
        nativeCookie=result.cookie.split(";",2)[0];
        CookieManager cookies=CookieManager.getInstance();cookies.setAcceptCookie(true);
        cookies.setCookie(AuthHttp.ORIGIN,result.cookie,accepted->{
            if(!active(version,generation))return;
            if(!accepted){showFailure("Не удалось восстановить веб-сессию.",true);return;}
            cookies.flush();if(!pageLoaded&&web!=null){View bar=root.findViewWithTag("updates");if(bar!=null)root.removeView(bar);root.removeView(web);web.stopLoading();web.removeJavascriptInterface("AndroidAuth");web.destroy();web=null;}ensureWeb();web.getSettings().setBlockNetworkLoads(false);
            loading=true;pageEpoch=version;
            if(!pageLoaded)web.loadUrl(AuthHttp.ORIGIN+"/");
            else resumePage(version,generation);
            if(active(version,generation)){ui.removeCallbacks(renewal);ui.postDelayed(renewal,2*60*60*1000L);}
        });
    }
    private void resumePage(long version,long generation){
        web.evaluateJavascript("(function(){const version="+version+";window.aiControlAndroidResumeResult={version:version,ok:null};function done(ok){if(window.aiControlAndroidResumeResult.version===version)window.aiControlAndroidResumeResult.ok=ok;}if(window.aiControlAndroidResume)window.aiControlAndroidResume().then(done);else done(\"missing\");})();",null);awaitResume(version,generation,0);
    }
    private void awaitResume(long version,long generation,int attempts){
        if(!active(version,generation)||web==null)return;
        web.evaluateJavascript("window.aiControlAndroidResumeResult && window.aiControlAndroidResumeResult.version==="+version+" ? window.aiControlAndroidResumeResult.ok : null",value->{
            if(!active(version,generation))return;
            if("true".equals(value)){loading=false;hideOverlay();}
            else if("\"missing\"".equals(value)){pageLoaded=false;loading=false;showFailure("Серверная панель требует обновления. Повторите подключение после обновления сервера.",true);}
            else if("false".equals(value)||attempts>=100){loading=false;showFailure("Не удалось восстановить панель. Повторите подключение.",true);}
            else ui.postDelayed(()->awaitResume(version,generation,attempts+1),100);
        });
    }
    private void hideOverlay(){if(overlay!=null){root.removeView(overlay);overlay=null;}}
    private final class Bridge {
        private final WebView owner;Bridge(WebView owner){this.owner=owner;}
        @JavascriptInterface public void requestAuth(){ui.post(()->{if(owner==web&&foreground)admit(false);});}
        @JavascriptInterface public void requestLogout(){ui.post(()->{if(owner==web)logout();});}
    }
    private void ensureWeb(){if(web!=null)return;
        web=new WebView(this);WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        WebSettings settings=web.getSettings();settings.setJavaScriptEnabled(true);settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSafeBrowsingEnabled(true);settings.setSupportMultipleWindows(false);settings.setJavaScriptCanOpenWindowsAutomatically(false);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web,false);
        web.addJavascriptInterface(new Bridge(web),"AndroidAuth");
        final WebView instance=web;final long createdEpoch=epoch,createdGeneration=authGeneration;
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){
                if(view!=instance||!foreground||credential==null||!"ACTIVE".equals(credential.state))return true;
                NavigationDecision decision=OriginPolicy.INSTANCE.classify(request.getUrl().toString(),request.isForMainFrame(),request.hasGesture(),request.getMethod(),request.isRedirect());
                if(decision==NavigationDecision.OPEN_BROWSER){try{startActivity(new Intent(Intent.ACTION_VIEW,request.getUrl()).addCategory(Intent.CATEGORY_BROWSABLE));}catch(ActivityNotFoundException ignored){new AlertDialog.Builder(MainActivity.this).setMessage("Не найден браузер для открытия ссылки.").setPositiveButton("Закрыть",null).show();}return true;}
                return decision!=NavigationDecision.ALLOW_PANEL;
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest request){
                if(view!=instance||view!=web||!foreground||credential==null||!"ACTIVE".equals(credential.state)||OriginPolicy.INSTANCE.classify(request.getUrl().toString(),request.isForMainFrame(),false,request.getMethod(),request.isRedirect())!=NavigationDecision.ALLOW_PANEL)
                    return new WebResourceResponse("text/plain","UTF-8",403,"Blocked",java.util.Collections.emptyMap(),new ByteArrayInputStream(new byte[0]));
                return null;
            }
            private boolean viewCurrent(){return web==instance;}
            private void failedPage(){if(viewCurrent()&&foreground&&pageEpoch==epoch){loading=false;pageLoaded=false;showFailure("Не удалось загрузить панель. Повторите подключение.",true);}}
            @Override public void onReceivedError(WebView view,WebResourceRequest request,WebResourceError error){if(request.isForMainFrame())failedPage();}
            @Override public void onReceivedHttpError(WebView view,WebResourceRequest request,WebResourceResponse response){if(request.isForMainFrame())failedPage();}
            @Override public void onReceivedSslError(WebView view,SslErrorHandler handler,SslError error){handler.cancel();if(view==instance&&view==web&&error.getUrl()!=null&&error.getUrl().equals(view.getUrl()))failedPage();}
            @Override public void onPageFinished(WebView view,String url){if(viewCurrent()&&!pageLoaded&&foreground&&createdEpoch==epoch&&pageEpoch==epoch&&url.equals(AuthHttp.ORIGIN+"/")&&loading){pageLoaded=true;resumePage(createdEpoch,createdGeneration);}}
            @Override public boolean onRenderProcessGone(WebView view,RenderProcessGoneDetail detail){if(!viewCurrent())return true;destroyPage();loading=false;showFailure("Панель закрылась. Повторите подключение.",true);return true;}
            @Override public void onPageStarted(WebView view,String url,android.graphics.Bitmap icon){
                if(view!=instance||!foreground||credential==null||!"ACTIVE".equals(credential.state))return;
                if(OriginPolicy.INSTANCE.classify(url,true,false,"GET",false)!=NavigationDecision.ALLOW_PANEL){view.stopLoading();showFailure("Переход заблокирован.",true);}
            }
        });
        web.setWebChromeClient(new WebChromeClient());FrameLayout.LayoutParams layout=new FrameLayout.LayoutParams(-1,-1);layout.topMargin=(int)(44*getResources().getDisplayMetrics().density);root.addView(web,0,layout);
        Button updates=new Button(this);updates.setText("Обновления");updates.setOnClickListener(v->startActivity(new Intent(this,UpdatesActivity.class)));updates.setTag("updates");FrameLayout.LayoutParams bar=new FrameLayout.LayoutParams(-1,layout.topMargin,Gravity.TOP);root.addView(updates,1,bar);
    }
    private void destroyPage(){View bar=root.findViewWithTag("updates");if(bar!=null)root.removeView(bar);nativeCookie=null;pageLoaded=false;if(web!=null){root.removeView(web);web.stopLoading();web.removeJavascriptInterface("AndroidAuth");web.clearHistory();web.clearCache(true);web.destroy();web=null;}WebStorage.getInstance().deleteAllData();}
    private void terminal(){epoch++;gate.deny();destroyPage();
        try{store.clear();credential=null;}catch(Exception e){storageBroken=true;showFailure("Не удалось удалить сохраненный вход. Очистите данные приложения.",false);return;}
        clearPending=true;CookieManager.getInstance().removeAllCookies(ok->{clearPending=false;CookieManager.getInstance().flush();if(foreground&&credential==null&&!storageBroken)showLogin();});
    }
    private void logout(){if(!foreground||credential==null||!"ACTIVE".equals(credential.state))return;
        epoch++;loading=false;gate.logout();ui.removeCallbacks(renewal);if(web!=null)web.getSettings().setBlockNetworkLoads(true);
        try{store.save(credential.token,"PENDING_LOGOUT");credential=new CredentialStore.Record(credential.token,"PENDING_LOGOUT");revoke();}
        catch(Exception e){showFailure("Не удалось сохранить выход. Очистите данные приложения или перезапустите и повторите выход.",false);}
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
