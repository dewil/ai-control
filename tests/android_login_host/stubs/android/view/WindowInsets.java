package android.view;
public class WindowInsets {
 final int left,top,right,bottom,ime;
 public WindowInsets(int l,int t,int r,int b,int keyboard){left=l;top=t;right=r;bottom=b;ime=keyboard;}
 public int getSystemWindowInsetLeft(){return left;} public int getSystemWindowInsetTop(){return top;} public int getSystemWindowInsetRight(){return right;} public int getSystemWindowInsetBottom(){return bottom;}
 public android.graphics.Insets getInsets(int mask){return new android.graphics.Insets(left,top,right,(mask&2)!=0?Math.max(bottom,ime):bottom);}
 public boolean isVisible(int mask){return (mask&2)!=0 && ime>0;}
 public static class Type {public static int systemBars(){return 1;}public static int ime(){return 2;}}
}
