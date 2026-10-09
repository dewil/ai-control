package android.net;
/** Real URI parsing for the host security oracle, not Android SDK throwing stubs. */
public final class Uri {
 private final java.net.URI value;private Uri(String text){value=java.net.URI.create(text);}public static Uri parse(String text){return new Uri(text);}
 public String getScheme(){return value.getScheme();}public String getHost(){return value.getHost();}public int getPort(){return value.getPort();}public String getPath(){return value.getPath();}public String getEncodedPath(){return value.getRawPath();}public String getQuery(){return value.getRawQuery();}public String getEncodedQuery(){return value.getRawQuery();}public String getFragment(){return value.getFragment();}public String getAuthority(){return value.getRawAuthority();}public String toString(){return value.toString();}
}
