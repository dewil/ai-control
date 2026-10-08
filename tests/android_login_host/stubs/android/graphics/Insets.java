package android.graphics;
public final class Insets {public final int left,top,right,bottom;public Insets(int l,int t,int r,int b){left=l;top=t;right=r;bottom=b;}public static Insets of(int l,int t,int r,int b){return new Insets(l,t,r,b);} }
