package android.webkit;
/** Author-only controllable delivery of the real native cookie callback. */
public class CookieManager {
 private static final CookieManager instance=new CookieManager();
 public static boolean hold=false;public static ValueCallback<Boolean> pending;
 public static CookieManager getInstance(){return instance;}
 public void setAcceptCookie(boolean value){}public void setAcceptThirdPartyCookies(WebView view,boolean value){}
 public void setCookie(String origin,String cookie,ValueCallback<Boolean> callback){if(hold)pending=callback;else callback.onReceiveValue(true);}
 public String getCookie(String origin){return "control_session=synthetic-only";}
 public void flush(){}public void removeAllCookies(ValueCallback<Boolean> callback){callback.onReceiveValue(true);}
}
