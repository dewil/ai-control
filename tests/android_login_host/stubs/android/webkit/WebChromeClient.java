package android.webkit;import android.content.Intent;import android.net.Uri;public class WebChromeClient {
 public boolean onShowFileChooser(WebView v,ValueCallback<Uri[]> callback,FileChooserParams p){return false;}
 public abstract static class FileChooserParams {
 public static final int MODE_OPEN=0,MODE_OPEN_MULTIPLE=1,MODE_SAVE=3;public abstract int getMode();public abstract String[] getAcceptTypes();public abstract boolean isCaptureEnabled();public abstract CharSequence getTitle();public abstract String getFilenameHint();public abstract Intent createIntent();
 public static Uri[] parseResult(int result,Intent data){if(result!=-1||data==null)return null;if(data.getClipData()!=null){android.content.ClipData c=data.getClipData();Uri[] values=new Uri[c.getItemCount()];for(int i=0;i<values.length;i++)values[i]=c.getItemAt(i).getUri();return values;}return data.getData()==null?null:new Uri[]{data.getData()};}
 }}