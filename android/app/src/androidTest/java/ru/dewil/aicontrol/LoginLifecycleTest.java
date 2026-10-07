package ru.dewil.aicontrol;

import static org.junit.Assert.*;
import android.app.Instrumentation;
import android.content.Intent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.TextView;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import org.junit.Test;
import org.junit.runner.RunWith;

/** INV-AND-13 INV-AND-14 INV-APP-06. Synthetic debug-app fixture only.
 * Controlled same-Activity lifecycle is not proof of real KeePass/device UX. */
@RunWith(AndroidJUnit4.class)
public final class LoginLifecycleTest {
    private static View text(View view, String value, boolean hint) {
        if (view instanceof TextView) {
            CharSequence found = hint ? ((TextView)view).getHint() : ((TextView)view).getText();
            if (found != null && value.contentEquals(found)) return view;
        }
        if (view instanceof ViewGroup) {
            ViewGroup group=(ViewGroup)view;
            for(int i=0;i<group.getChildCount();i++) {
                View found=text(group.getChildAt(i),value,hint);
                if(found!=null)return found;
            }
        }
        return null;
    }
    private MainActivity launch(Instrumentation instrumentation) {
        Intent intent=new Intent(instrumentation.getTargetContext(),MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        return (MainActivity)instrumentation.startActivitySync(intent);
    }
    @Test public void sameActivityRetainsExactLoginValuesFocusAndSelection() {
        Instrumentation instrumentation=InstrumentationRegistry.getInstrumentation();
        MainActivity activity=launch(instrumentation);
        try {
            instrumentation.runOnMainSync(()->{
                View root=activity.getWindow().getDecorView();
                EditText username=(EditText)text(root,"Логин",true);
                EditText password=(EditText)text(root,"Пароль",true);
                EditText totp=(EditText)text(root,"Код TOTP",true);
                assertNotNull("Requires empty debug-app credential store",username);
                username.setText("  Synthetic User  ");
                instrumentation.callActivityOnStop(activity);
                instrumentation.callActivityOnStart(activity);
                assertSame(username,text(root,"Логин",true));
                assertEquals("  Synthetic User  ",username.getText().toString());
                password.setText(" synthetic-password-fixture ");
                password.requestFocus();password.setSelection(2,5);
                instrumentation.callActivityOnStop(activity);
                instrumentation.callActivityOnStart(activity);
                assertSame(password,text(root,"Пароль",true));
                assertEquals(" synthetic-password-fixture ",password.getText().toString());
                assertTrue(password.hasFocus());assertEquals(2,password.getSelectionStart());assertEquals(5,password.getSelectionEnd());
                totp.setText("123456");
                instrumentation.callActivityOnStop(activity);
                instrumentation.callActivityOnStart(activity);
                assertSame(totp,text(root,"Код TOTP",true));
                assertEquals("123456",totp.getText().toString());
            });
        } finally {instrumentation.runOnMainSync(activity::finish);}
    }
    @Test public void updateEntryIsBelowSubmitWithAccessibleTouchTarget() {
        Instrumentation instrumentation=InstrumentationRegistry.getInstrumentation();
        MainActivity activity=launch(instrumentation);
        try {
            instrumentation.waitForIdleSync();
            instrumentation.runOnMainSync(()->{
                View root=activity.getWindow().getDecorView();
                View submit=text(root,"Войти",false),entry=text(root,"Обновления приложения",false);
                assertNotNull(submit);assertNotNull(entry);
                int[] submitPosition=new int[2],entryPosition=new int[2];
                submit.getLocationOnScreen(submitPosition);entry.getLocationOnScreen(entryPosition);
                assertTrue("Updates needs spacing below submit",entryPosition[1]>submitPosition[1]+submit.getHeight());
                assertTrue("Updates touch target must be at least48dp",entry.getHeight()>=48*activity.getResources().getDisplayMetrics().density);
                assertTrue(entry.isClickable());assertTrue(entry.isFocusable());
            });
        } finally {instrumentation.runOnMainSync(activity::finish);}
    }
}
