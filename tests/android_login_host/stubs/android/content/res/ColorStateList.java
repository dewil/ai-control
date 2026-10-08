package android.content.res;
/** Android public state-list metadata: default is the empty state specification. */
public class ColorStateList {
 final int[][] states;final int[] colors;
 public ColorStateList(int[][] specs,int[] values){states=specs;colors=values;}
 public int getDefaultColor(){for(int i=0;i<states.length;i++)if(states[i].length==0)return colors[i];return colors[0];}
 public boolean isStateful(){for(int[] state:states)if(state.length>0)return true;return false;}
 public int getColorForState(int[] active,int fallback){for(int i=0;i<states.length;i++){boolean match=true;for(int wanted:states[i]){boolean present=false;for(int value:active)if(value==Math.abs(wanted))present=true;if(present!=(wanted>0))match=false;}if(match)return colors[i];}return fallback;}
}
