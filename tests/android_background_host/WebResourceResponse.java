package android.webkit;
public class WebResourceResponse {
 public String mime,encoding;public int status;public java.io.InputStream data;
 public WebResourceResponse(String mime,String encoding,java.io.InputStream data){this.mime=mime;this.encoding=encoding;this.data=data;status=200;}
 public WebResourceResponse(String mime,String encoding,int status,String reason,java.util.Map<String,String> headers,java.io.InputStream data){this(mime,encoding,data);this.status=status;}
 public int getStatusCode(){return status;}public java.io.InputStream getData(){return data;}
}
