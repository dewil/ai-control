package ru.dewil.aicontrol;
/** Author-only status control, synthetic native auth with no real network/storage. */
public class AuthHttp {
 public static final String ORIGIN="https://llm-web.dewil.ru:18443";public static int calls=0,status=200;
 public static class Result {public int status;public String cookie="control_session=synthetic-only; Path=/; Secure; HttpOnly";public org.json.JSONObject body=new org.json.JSONObject();}
 public static Result post(String path,String token,String cookie,org.json.JSONObject body){calls++;Result value=new Result();value.status=status;try{
  if(status==200){if(path.equals("/api/app/login"))value.body.put("device_token","synthetic-device-fixture");else{value.body.put("status","ok");if(path.equals("/api/app/session"))value.body.put("session_replaced",true);}}
  else value.body.put("error","unavailable");
 }catch(Exception error){throw new RuntimeException(error);}return value;}
}
