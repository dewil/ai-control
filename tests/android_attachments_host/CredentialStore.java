package ru.dewil.aicontrol;
public class CredentialStore {public static int clears=0;public CredentialStore(android.content.Context c){} public static class Record {public String token,state;public Record(String t,String s){token=t;state=s;}}public Record load(){return null;}public void save(String t,String s){}public void clear(){clears++;} }
