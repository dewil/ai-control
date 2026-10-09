package android.os;
/** Host monotonic clock; historical UI probes do not control lifecycle deadlines. */
public final class SystemClock {
 private static final long START=System.nanoTime();
 public static long elapsedRealtimeNanos(){return System.nanoTime()-START;}
 public static long elapsedRealtime(){return elapsedRealtimeNanos()/1000000L;}
 public static long uptimeMillis(){return elapsedRealtime();}
}
