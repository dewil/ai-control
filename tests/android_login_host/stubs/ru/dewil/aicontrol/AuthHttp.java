package ru.dewil.aicontrol;
public class AuthHttp {public static final String ORIGIN="https://fixture.invalid";public static class Result {public int status=401; public String cookie; public org.json.JSONObject body=new org.json.JSONObject();} public static Result post(String path,String token,String cookie,org.json.JSONObject body){return new Result();} }
