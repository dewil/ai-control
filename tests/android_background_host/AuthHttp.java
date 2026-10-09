package ru.dewil.aicontrol;
public class AuthHttp {
 public static final String ORIGIN="https://llm-web.dewil.ru:18443";public static int calls=0;
 public static class Result {public int status=200;public String cookie="control_session=synthetic-only; Path=/; Secure; HttpOnly";public org.json.JSONObject body=new org.json.JSONObject();}
 public static Result post(String path,String token,String cookie,org.json.JSONObject body){calls++;Result r=new Result();try{
  if(path.equals("/api/app/login"))r.body.put("device_token","synthetic-device-fixture");
  else {r.body.put("status","ok");if(path.equals("/api/app/session"))r.body.put("session_replaced",true);}
 }catch(Exception e){throw new RuntimeException(e);}return r;}
}
