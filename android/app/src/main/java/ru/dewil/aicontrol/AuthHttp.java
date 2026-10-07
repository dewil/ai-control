package ru.dewil.aicontrol;

import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import android.os.SystemClock;
import org.json.JSONObject;

/** Fixed-origin transport, never forwards bearer or cookie through redirects. */
final class AuthHttp {
    private static final java.util.concurrent.ScheduledExecutorService deadlines=java.util.concurrent.Executors.newSingleThreadScheduledExecutor(r->{Thread thread=new Thread(r,"auth-deadline");thread.setDaemon(true);return thread;});
    static final String ORIGIN="https://llm-web.dewil.ru:18443";
    static final class Result {
        final int status; final JSONObject body; final String cookie;
        Result(int status,JSONObject body,String cookie){this.status=status;this.body=body;this.cookie=cookie;}
    }
    static Result post(String path,String token,String cookie,JSONObject body) throws Exception {
        if(!path.equals("/api/app/login")&&!path.equals("/api/app/session")&&!path.equals("/api/app/logout"))
            throw new IOException("Authentication unavailable");
        HttpURLConnection c=(HttpURLConnection)new URL(ORIGIN+path).openConnection();
        java.util.concurrent.ScheduledFuture<?> timeout=deadlines.schedule(c::disconnect,20,java.util.concurrent.TimeUnit.SECONDS);
        try {
            c.setInstanceFollowRedirects(false); c.setRequestMethod("POST");
            c.setConnectTimeout(10000);c.setReadTimeout(10000);c.setDoOutput(true);
            c.setRequestProperty("Origin",ORIGIN);c.setRequestProperty("Content-Type","application/json");
            if(token!=null)c.setRequestProperty("Authorization","Bearer "+token);
            if(cookie!=null && path.equals("/api/app/session"))c.setRequestProperty("Cookie",cookie);
            byte[] data=body.toString().getBytes(StandardCharsets.UTF_8);
            c.setFixedLengthStreamingMode(data.length);
            long deadline=SystemClock.elapsedRealtime()+20000;
            try(OutputStream out=c.getOutputStream()){out.write(data);}
            int status=c.getResponseCode();
            if(status>=300&&status<400)throw new IOException("Authentication unavailable");
            InputStream stream=status>=400?c.getErrorStream():c.getInputStream();
            if(stream==null)throw new IOException("Authentication unavailable");
            ByteArrayOutputStream bytes=new ByteArrayOutputStream();
            try(InputStream in=stream){byte[] buffer=new byte[4096];int n;
                while((n=in.read(buffer))!=-1){
                    if(bytes.size()+n>16384||SystemClock.elapsedRealtime()>deadline)
                        throw new IOException("Authentication unavailable");
                    bytes.write(buffer,0,n);
                }
            }
            if(SystemClock.elapsedRealtime()>deadline)throw new IOException("Authentication unavailable");
            JSONObject json=new JSONObject(bytes.toString("UTF-8"));
            String accepted=null;
            java.util.List<String> cookies=c.getHeaderFields().get("Set-Cookie");
            if(cookies==null)cookies=c.getHeaderFields().get("set-cookie");
            if(cookies!=null)for(String value:cookies){
                String[] parts=value.split(";");
                if(!parts[0].matches("control_session=[A-Za-z0-9_-]{43}"))continue;
                boolean secure=false,httpOnly=false,pathRoot=false,domain=false;
                for(int i=1;i<parts.length;i++){
                    String attr=parts[i].trim().toLowerCase(java.util.Locale.ROOT);
                    secure|=attr.equals("secure");httpOnly|=attr.equals("httponly");
                    pathRoot|=attr.equals("path=/");domain|=attr.startsWith("domain=");
                }
                if(secure&&httpOnly&&pathRoot&&!domain)accepted=value;
            }
            return new Result(status,json,accepted);
        } finally {timeout.cancel(false);c.disconnect();}
    }
}
