package ru.dewil.aicontrol;
import android.view.View;
import android.view.WindowInsets;
import android.widget.ScrollView;
/** INV-AND-16 / ANDROID-UX-SOURCE-02: actual Activity insets/density/scroll root. */
public final class UpdatesInsetsProbe {
 public static void main(String[] args)throws Exception{
  UpdatesActivity activity=new UpdatesActivity();try{
   activity.onCreate(null);View root=activity.getWindow().getDecorView();
   if(args[0].equals("scroll")){
    LoginLifecycleProbe.check(root instanceof ScrollView,"Updates controls have no native scrolling path in small landscape viewport");
    LoginLifecycleProbe.check(((ScrollView)root).getChildCount()==1,"Scroll root must retain its complete content column");
   }else if(args[0].equals("insets")){
    int left=root.getPaddingLeft(),top=root.getPaddingTop(),right=root.getPaddingRight(),bottom=root.getPaddingBottom();
    WindowInsets bars=new WindowInsets(12,24,18,32,180);
    root.dispatchApplyWindowInsets(bars);
    LoginLifecycleProbe.check(root.getPaddingLeft()>=left+12 && root.getPaddingTop()>=top+24 && root.getPaddingRight()>=right+18,"Updates content does not account for system bar insets");
    LoginLifecycleProbe.check(root.getPaddingBottom()>=bottom+(android.os.Build.VERSION.SDK_INT>=30?180:32),"Updates content ignores required keyboard/navigation inset");
    int after=root.getPaddingBottom();root.dispatchApplyWindowInsets(bars);
    LoginLifecycleProbe.check(root.getPaddingBottom()==after,"Repeated insets accumulate and consume viewport");
   }else{
    int left=root.getPaddingLeft(),top=root.getPaddingTop(),right=root.getPaddingRight(),bottom=root.getPaddingBottom();
    android.util.DisplayMetrics.fixtureDensity=2;
    UpdatesActivity dense=new UpdatesActivity();try{dense.onCreate(null);View second=dense.getWindow().getDecorView();
     LoginLifecycleProbe.check(Math.abs(second.getPaddingLeft()-2*left)<=1 && Math.abs(second.getPaddingTop()-2*top)<=1 && Math.abs(second.getPaddingRight()-2*right)<=1 && Math.abs(second.getPaddingBottom()-2*bottom)<=1,"Updates native content uses fixed pixel padding instead of density-scaled spacing");
     LoginLifecycleProbe.check(left+top+right+bottom>0,"Spacing probe requires nonzero native padding");
    }finally{dense.onDestroy();}
   }
   System.out.println("PASS updates "+args[0]+" SDK"+android.os.Build.VERSION.SDK_INT);
  }finally{activity.onDestroy();}
 }
}
