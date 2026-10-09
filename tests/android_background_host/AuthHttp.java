package ru.dewil.aicontrol;
public class AuthHttp {
 public static final String ORIGIN="https://fixture.invalid";public static int calls=0;
 public static class Result {public int status=200;public String cookie="control_session=synthetic-only; Path=/; Secure; HttpOnly";public org.json.JSONObject body=new org.json.JSONObject();}
 public static Result post(String path,String token,String cookie,org.json.JSONObject body){calls++;Result r=new Result();try{r.body.put("device_token","synthetic-device-fixture");r.body.put("cookie_replaced",true);}catch(Exception e){throw new RuntimeException(e);}return r;}
}
