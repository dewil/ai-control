package ru.dewil.aicontrol;
import android.webkit.*;import android.net.Uri;import java.util.*;
/** INV-WATT-09 real MainActivity through public lifecycle and interceptor APIs. */
public final class UploadChunkInterceptorProbe {
 static final String ROUTE="/api/session-attachment-chunk?attachment_id=00000000-0000-4000-8000-000000000001&index=0";
 static void check(boolean value,String reason){if(!value)throw new AssertionError("INV-WATT-09: "+reason);}
 static WebResourceRequest request(String url,boolean main,boolean redirect){return new WebResourceRequest(){public Uri getUrl(){return Uri.parse(url);}public boolean isForMainFrame(){return main;}public boolean isRedirect(){return redirect;}public boolean hasGesture(){return false;}public String getMethod(){return "PUT";}public Map<String,String> getRequestHeaders(){return Collections.emptyMap();}};}
 public static void main(String[] args){try{run(args[0]);System.out.println("PASS "+args[0]);System.exit(0);}catch(Throwable error){error.printStackTrace();System.exit(1);}}
 static void run(String name)throws Exception {
  MainActivity activity=BackgroundProbe.login(true);WebView page=BackgroundProbe.page();int authCalls=AuthHttp.calls;String origin=AuthHttp.ORIGIN;
  if(name.equals("active"))check(page.client.shouldInterceptRequest(page,request(origin+ROUTE,false,false))==null,"ACTIVE upload chunk PUT was replaced by native blocked/empty response");
  else if(name.equals("inactive")){BackgroundProbe.pause(activity);check(page.client.shouldInterceptRequest(page,request(origin+ROUTE,false,false))!=null,"background upload bypassed native lifecycle block");}
  else if(name.equals("boundaries")){
   for(String url:new String[]{"https://foreign.invalid"+ROUTE,origin+"/api/session-send",origin+"/download/android/",origin+ROUTE+"#fragment",origin+"/api/session-attachment-chunk/extra"})check(page.client.shouldInterceptRequest(page,request(url,false,false))!=null,"PUT admitted foreign/other/fragment route "+url);
   check(page.client.shouldInterceptRequest(page,request(origin+ROUTE,true,false))!=null,"PUT admitted main-frame navigation");
   check(page.client.shouldInterceptRequest(page,request(origin+ROUTE,false,true))!=null,"PUT admitted redirect");
  }else throw new AssertionError("unknown case");
  check(AuthHttp.calls==authCalls,"upload policy touched native auth");
 }
}
