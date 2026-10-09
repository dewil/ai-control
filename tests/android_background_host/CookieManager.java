package android.webkit;
public class CookieManager {
 private static CookieManager instance=new CookieManager();public static boolean accept=true;
 public static CookieManager getInstance(){return instance;}public void setAcceptCookie(boolean b){}public void setAcceptThirdPartyCookies(WebView v,boolean b){}
 public void setCookie(String u,String v,ValueCallback<Boolean> c){if(c!=null)c.onReceiveValue(accept);}public String getCookie(String u){return "control_session=synthetic-only";}
 public void flush(){}public void removeAllCookies(ValueCallback<Boolean> c){if(c!=null)c.onReceiveValue(true);}
}
