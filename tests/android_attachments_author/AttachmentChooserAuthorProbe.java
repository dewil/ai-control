package ru.dewil.aicontrol;
import android.content.*;
import android.webkit.*;
import androidx.activity.ComponentActivity;
/** INV-WATT-09: supplementary lifecycle ordering and stale request correlation. */
public final class AttachmentChooserAuthorProbe {
 static void check(boolean value,String message){AttachmentChooserProbe.check(value,message);}
 static void resume(MainActivity a,WebView p)throws Exception {
  long old=BackgroundProbe.serial(BackgroundProbe.latest(p));
  a.onStart();BackgroundProbe.lifecycle(a,"onResume");
  long deadline=System.nanoTime()+2_000_000_000L;
  while(System.nanoTime()<deadline){android.os.Handler.runPosted();if(BackgroundProbe.serial(BackgroundProbe.latest(p))>old)break;Thread.sleep(2);}
  WebView.Eval suspend=BackgroundProbe.latest(p);
  check(suspend.script.contains("aiControlAndroidSuspend")&&BackgroundProbe.serial(suspend)>old,"fresh suspend missing");
  suspend.callback.onReceiveValue(BackgroundProbe.ack(BackgroundProbe.serial(suspend)));
  BackgroundProbe.completeResume(p,"admit");BackgroundProbe.completeResume(p,"activate");
 }
 public static void main(String[] args){try{
  MainActivity a=BackgroundProbe.login(true);WebView p=BackgroundProbe.page();AttachmentChooserProbe.Capture c=new AttachmentChooserProbe.Capture();
  AttachmentChooserProbe.launch(p,c,true);
  if(args[0].equals("before-resume")){
   BackgroundProbe.pause(a);a.onStop();a.deliverResult(-1,AttachmentChooserProbe.single());
   check(c.calls==0,"result crossed background admission fence");resume(a,p);
   check(c.calls==1&&c.value!=null,"pre-resume result lost after activation");a.deliverResult(-1,AttachmentChooserProbe.single());check(c.calls==1,"pre-resume duplicate redelivered");
  }else if(args[0].equals("replace-late")){
   int old=a.requestCode;AttachmentChooserProbe.Capture next=new AttachmentChooserProbe.Capture();AttachmentChooserProbe.launch(p,next,true);
   java.lang.reflect.Method result=MainActivity.class.getDeclaredMethod("onActivityResult",int.class,int.class,Intent.class);result.setAccessible(true);result.invoke(a,old,-1,AttachmentChooserProbe.single());
   check(c.calls==1&&c.value==null&&next.calls==0,"old request satisfied successor");AttachmentChooserProbe.singleResult(a,next);
  }else if(args[0].equals("cancel-background")){
   BackgroundProbe.pause(a);a.onStop();a.deliverResult(0,null);check(c.calls==1&&c.value==null,"background cancel retained callback");
  }else if(args[0].equals("huge-count")){
   ClipData clip=new ClipData("files",new String[]{"*/*"},new ClipData.Item(AttachmentChooserProbe.uri("one"))){
    public int getItemCount(){return Integer.MAX_VALUE;}
    public ClipData.Item getItemAt(int n){throw new AssertionError("over-limit result iterated");}
   };
   a.deliverResult(-1,new Intent().setClipData(clip));check(c.calls==1&&c.value==null,"unbounded provider count accepted");
  }else if(args[0].equals("nine-files")||args[0].equals("eight-files")){
   int count=args[0].equals("nine-files")?9:8;ClipData clip=ClipData.newRawUri("files",AttachmentChooserProbe.uri("0"));
   for(int i=1;i<count;i++)clip.addItem(new ClipData.Item(AttachmentChooserProbe.uri(""+i)));
   a.deliverResult(-1,new Intent().setClipData(clip));check(c.calls==1,"bounded selection callback missing");
   check(count==8?c.value!=null&&c.value.length==8:c.value==null,"selection limit boundary incorrect");
  }else if(args[0].equals("mixed-uri")){
   ClipData clip=ClipData.newRawUri("files",AttachmentChooserProbe.uri("one"));clip.addItem(new ClipData.Item(android.net.Uri.parse("https://invalid.example/file")));
   a.deliverResult(-1,new Intent().setClipData(clip));check(c.calls==1&&c.value==null,"mixed URI provider selection partly accepted");
  }else throw new AssertionError("Unknown test");
  System.out.println("PASS "+args[0]);System.exit(0);
 }catch(Throwable e){e.printStackTrace();System.exit(1);}}
}
