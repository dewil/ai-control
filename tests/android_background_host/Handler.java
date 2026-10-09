package android.os;
import java.util.*;
/** Virtual UI scheduler: no sleeps, callbacks independent of WebView response. */
public class Handler {
  static class Due {Runnable r;long at;Due(Runnable r,long at){this.r=r;this.at=at;}}
  static List<Due> work=new ArrayList<>();public static long now=0;private Looper looper;
  public Handler(Looper l){looper=l;}public Looper getLooper(){return looper;}
  public static Handler createAsync(Looper l){return new Handler(l);}
  public synchronized boolean post(Runnable r){synchronized(work){work.add(new Due(r,now));}return true;}
  public boolean postDelayed(Runnable r,long delay){synchronized(work){work.add(new Due(r,now+delay));}return true;}
  public void removeCallbacks(Runnable r){synchronized(work){work.removeIf(d->d.r==r);}}
  public void removeCallbacksAndMessages(Object token){synchronized(work){work.clear();}}
  public static void runPosted(){advance(0);}
  public static void advance(long delta){now+=delta;for(int i=0;i<1000;i++){Due next=null;synchronized(work){for(Due d:work)if(d.at<=now){next=d;break;}if(next!=null)work.remove(next);}if(next==null)return;next.r.run();}throw new AssertionError("Unbounded UI callback loop");}
}
