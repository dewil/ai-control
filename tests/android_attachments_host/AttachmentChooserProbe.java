package ru.dewil.aicontrol;
import android.content.*;
import android.net.Uri;
import android.webkit.*;
import androidx.activity.ComponentActivity;
import java.util.*;
/** INV-WATT-09: real Activity, public WebChromeClient callback, synthetic provider. */
public final class AttachmentChooserProbe {
 static void check(boolean v,String message){if(!v)throw new AssertionError("INV-WATT-09: "+message);}
 static class Capture implements ValueCallback<Uri[]> {int calls=0;Uri[] value;public void onReceiveValue(Uri[] v){calls++;value=v;check(calls<=1,"chooser callback completed more than once");}}
 static class Params extends WebChromeClient.FileChooserParams {
  final boolean multiple;Params(boolean m){multiple=m;}public int getMode(){return multiple?MODE_OPEN_MULTIPLE:MODE_OPEN;}public String[] getAcceptTypes(){return new String[]{"*/*"};}public boolean isCaptureEnabled(){return false;}public CharSequence getTitle(){return "Synthetic documents";}public String getFilenameHint(){return null;}public Intent createIntent(){return new Intent(Intent.ACTION_GET_CONTENT).setType("*/*");}
 }
 static void launch(WebView p,Capture c,boolean multiple){check(p.chrome!=null,"native page has no WebChromeClient");check(p.chrome.onShowFileChooser(p,c,new Params(multiple)),"public onShowFileChooser did not accept own authenticated page");check(c.calls==0,"callback completed before provider result");}
 static Intent picker(){Intent i=ComponentActivity.launched;if(i!=null&&Intent.ACTION_CHOOSER.equals(i.getAction()))i=i.getParcelableExtra(Intent.EXTRA_INTENT);check(i!=null,"no system picker intent launched");check(Intent.ACTION_OPEN_DOCUMENT.equals(i.getAction()),"picker must use ACTION_OPEN_DOCUMENT");check(i.hasCategory(Intent.CATEGORY_OPENABLE),"picker omitted CATEGORY_OPENABLE");check("*/*".equals(i.getType()),"arbitrary documents restricted by MIME");check((i.getFlags()&Intent.FLAG_GRANT_WRITE_URI_PERMISSION)==0,"picker requested write grant");return i;}
 static Uri uri(String name){return Uri.parse("content://synthetic.documents/document/"+name);}
 static Intent single(){return new Intent().setData(uri("one"));}
 static void singleResult(MainActivity a,Capture c)throws Exception{a.deliverResult(-1,single());check(c.calls==1&&c.value!=null&&c.value.length==1&&uri("one").toString().equals(c.value[0].toString()),"single content URI was lost or converted to a file path");}
 public static void main(String[] args){try{run(args[0]);System.out.println("PASS "+args[0]);System.exit(0);}catch(Throwable e){e.printStackTrace();System.exit(1);}}
 static void run(String test)throws Exception {
  MainActivity a=BackgroundProbe.login(true);WebView p=BackgroundProbe.page();Capture c=new Capture();int calls=AuthHttp.calls,clears=CredentialStore.clears,removed=CookieManager.removals;
  if(test.equals("foreign-view")){
   WebView foreign=new WebView(a);foreign.url=p.url;boolean accepted=p.chrome.onShowFileChooser(foreign,c,new Params(true));check(!accepted&&ComponentActivity.launches==0,"foreign WebView launched chooser");check(c.calls==0||c.calls==1&&c.value==null,"foreign callback got URI");return;
  }
  if(test.equals("foreign-origin")){
   p.url="https://untrusted.invalid/";boolean accepted=p.chrome.onShowFileChooser(p,c,new Params(true));check(!accepted&&ComponentActivity.launches==0,"foreign origin launched chooser");return;
  }
  if(test.equals("provider-unavailable")){
   ComponentActivity.providerUnavailable=true;p.chrome.onShowFileChooser(p,c,new Params(true));check(c.calls==1&&c.value==null,"missing provider did not release callback once");return;
  }
  launch(p,c,!test.equals("single"));Intent intent=picker();
  if(test.equals("multiple")){check(intent.getBooleanExtra(Intent.EXTRA_ALLOW_MULTIPLE,false),"multiple picker omitted EXTRA_ALLOW_MULTIPLE");ClipData clip=ClipData.newRawUri("files",uri("one"));clip.addItem(new ClipData.Item(uri("two")));a.deliverResult(-1,new Intent().setClipData(clip));check(c.calls==1&&c.value!=null&&c.value.length==2&&uri("two").toString().equals(c.value[1].toString()),"multiple content URIs/order lost");}
  else if(test.equals("cancel")){a.deliverResult(0,null);check(c.calls==1&&c.value==null,"cancel did not complete callback null");a.deliverResult(0,null);check(c.calls==1,"duplicate cancel invoked callback twice");}
  else if(test.equals("provider-error")){a.deliverResult(-1,new Intent(){public Uri getData(){throw new SecurityException("synthetic provider revoked grant");}});check(c.calls==1&&c.value==null,"provider failure leaked pending callback");}
  else if(test.equals("replace")){Capture next=new Capture();launch(p,next,true);check(c.calls==1&&c.value==null,"replacement failed to cancel prior callback exactly once");singleResult(a,next);check(c.calls==1,"new result redelivered old callback");}
  else if(test.equals("destroy")){a.onDestroy();check(c.calls==1&&c.value==null,"destroy failed to complete pending callback");a.deliverResult(-1,single());check(c.calls==1,"late result redelivered destroyed callback");}
  else if(test.equals("pause-return")){BackgroundProbe.pause(a);a.onStop();check(c.calls==0,"picker background lifecycle prematurely canceled pending selection");a.onStart();BackgroundProbe.lifecycle(a,"onResume");check(c.calls==0,"foreground return discarded pending selection");long deadline=System.nanoTime()+2_000_000_000L;while(System.nanoTime()<deadline){android.os.Handler.runPosted();if(AuthHttp.calls>calls&&!p.evals.isEmpty()&&BackgroundProbe.latest(p).script.contains("aiControlAndroidSuspend")){BackgroundProbe.latest(p).callback.onReceiveValue(BackgroundProbe.ack(BackgroundProbe.serial(BackgroundProbe.latest(p))));}if(!p.evals.isEmpty()&&BackgroundProbe.latest(p).script.contains("aiControlAndroidResume")){BackgroundProbe.completeResume(p,"admit");BackgroundProbe.completeResume(p,"activate");break;}Thread.sleep(2);}singleResult(a,c);check(!p.destroyed,"chooser return destroyed original page");return;}
  else if(test.equals("stale-page")){p.url=AuthHttp.ORIGIN+"/login";p.client.onPageStarted(p,p.url,null);a.deliverResult(-1,single());check(c.calls==1&&c.value==null,"late selection crossed navigation/auth fence");}
  else if(test.equals("bad-uri")){a.deliverResult(-1,new Intent().setData(Uri.parse("file:///private/synthetic.txt")));check(c.calls==1&&c.value==null,"provider returned non-content URI to webpage");}
  else if(test.equals("single")){singleResult(a,c);a.deliverResult(-1,single());check(c.calls==1,"duplicate result invoked callback twice");}
  else throw new AssertionError("unknown case "+test);
  if(!test.equals("stale-page"))check(AuthHttp.calls==calls&&CredentialStore.clears==clears&&CookieManager.removals==removed,"chooser modified login/session credentials");
 }
}
