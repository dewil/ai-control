package android.content;
import java.util.*;
public class Intent {
 public static final String ACTION_VIEW="android.intent.action.VIEW",ACTION_OPEN_DOCUMENT="android.intent.action.OPEN_DOCUMENT",ACTION_GET_CONTENT="android.intent.action.GET_CONTENT",ACTION_CHOOSER="android.intent.action.CHOOSER",CATEGORY_BROWSABLE="android.intent.category.BROWSABLE",CATEGORY_OPENABLE="android.intent.category.OPENABLE",EXTRA_ALLOW_MULTIPLE="android.intent.extra.ALLOW_MULTIPLE",EXTRA_INTENT="android.intent.extra.INTENT",EXTRA_MIME_TYPES="android.intent.extra.MIME_TYPES";
 public static final int FLAG_GRANT_READ_URI_PERMISSION=1,FLAG_GRANT_WRITE_URI_PERMISSION=2,FLAG_GRANT_PERSISTABLE_URI_PERMISSION=64;
 public Class<?> destination;private String action,type;private android.net.Uri data;private ClipData clip;private int flags;private Set<String> categories=new HashSet<>();private Map<String,Object> extras=new HashMap<>();
 public Intent(){}public Intent(String a){action=a;}public Intent(Context c,Class<?> cls){destination=cls;}public Intent(String a,android.net.Uri u){action=a;data=u;}
 public String getAction(){return action;}public Intent setAction(String a){action=a;return this;}public Intent addCategory(String c){categories.add(c);return this;}public Set<String> getCategories(){return categories;}public boolean hasCategory(String c){return categories.contains(c);}
 public Intent setType(String t){type=t;return this;}public String getType(){return type;}public Intent setData(android.net.Uri u){data=u;return this;}public android.net.Uri getData(){return data;}
 public Intent setClipData(ClipData c){clip=c;return this;}public ClipData getClipData(){return clip;}public Intent addFlags(int f){flags|=f;return this;}public Intent setFlags(int f){flags=f;return this;}public int getFlags(){return flags;}
 public Intent putExtra(String k,boolean v){extras.put(k,v);return this;}public Intent putExtra(String k,String[] v){extras.put(k,v);return this;}public Intent putExtra(String k,Intent v){extras.put(k,v);return this;}
 public boolean getBooleanExtra(String k,boolean d){return extras.containsKey(k)?(Boolean)extras.get(k):d;}public String[] getStringArrayExtra(String k){return (String[])extras.get(k);}
 @SuppressWarnings("unchecked") public <T> T getParcelableExtra(String k){return (T)extras.get(k);}public static Intent createChooser(Intent i,CharSequence title){return new Intent(ACTION_CHOOSER).putExtra(EXTRA_INTENT,i);}
}
