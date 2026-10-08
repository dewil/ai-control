package android.content.pm;
public class PackageManager {public static PackageInfo fixture;public static boolean failure;public static String queriedPackage="";public static class NameNotFoundException extends Exception {}public PackageInfo getPackageInfo(String name,int flags)throws NameNotFoundException {queriedPackage=name;if(failure)throw new NameNotFoundException();return fixture;} }
