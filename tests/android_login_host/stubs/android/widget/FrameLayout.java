package android.widget;
public class FrameLayout extends android.view.ViewGroup {public FrameLayout(android.content.Context c){super(c);} public static class LayoutParams extends android.view.ViewGroup.LayoutParams {public int topMargin,bottomMargin,gravity; public LayoutParams(int w,int h){super(w,h);} public LayoutParams(int w,int h,int g){super(w,h);gravity=g;} }}
