package android.webkit;
/** SDK signature with host-safe construction; no renderer simulation logic. */
public abstract class RenderProcessGoneDetail {
 public RenderProcessGoneDetail(){}
 public abstract boolean didCrash();
 public abstract int rendererPriorityAtExit();
}
