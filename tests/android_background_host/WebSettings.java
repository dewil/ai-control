package android.webkit;
public class WebSettings {
 public static final int MIXED_CONTENT_NEVER_ALLOW=1;public boolean blocked;public String ua="SyntheticWebView";public int id;
 public void setBlockNetworkLoads(boolean b){blocked=b;WebView.events.add(id+":block:"+b);}public boolean getBlockNetworkLoads(){return blocked;}
 public String getUserAgentString(){return ua;}public void setUserAgentString(String v){ua=v;}
 public void setJavaScriptEnabled(boolean b){}public void setDomStorageEnabled(boolean b){}public void setAllowFileAccess(boolean b){}public void setAllowContentAccess(boolean b){}public void setSafeBrowsingEnabled(boolean b){}public void setSupportMultipleWindows(boolean b){}public void setJavaScriptCanOpenWindowsAutomatically(boolean b){}public void setMixedContentMode(int i){}
}
