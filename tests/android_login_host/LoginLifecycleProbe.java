package ru.dewil.aicontrol;

import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import java.util.ArrayList;
import java.util.List;

/** Independent oracle for INV-AND-13 INV-AND-14 INV-APP-06; real MainActivity, synthetic values only. */
public final class LoginLifecycleProbe {
    static List<View> flatten(View view) {
        List<View> result = new ArrayList<>();
        result.add(view);
        if (view instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) view;
            for (int i = 0; i < group.getChildCount(); i++) result.addAll(flatten(group.getChildAt(i)));
        }
        return result;
    }
    static EditText field(MainActivity activity, String hint) {
        for (View view : flatten(activity.getWindow().getDecorView())) {
            if (view instanceof EditText && hint.contentEquals(((EditText)view).getHint())) return (EditText)view;
        }
        throw new AssertionError("Missing login field: " + hint);
    }
    static Button submit(MainActivity activity) {
        for (View view : flatten(activity.getWindow().getDecorView())) {
            if (view instanceof Button && "Войти".contentEquals(((Button)view).getText())) return (Button)view;
        }
        throw new AssertionError("Missing submit action");
    }
    static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    static void foreground(MainActivity activity) { activity.onStop(); activity.onStart(); }
    static void reset(MainActivity activity) throws Exception {
        java.lang.reflect.Method method = MainActivity.class.getDeclaredMethod("showLogin");
        method.setAccessible(true);
        method.invoke(activity);
    }
    public static void main(String[] args) throws Exception {
        MainActivity activity = new MainActivity();
        try {
            activity.onCreate(null);
            EditText initial = field(activity, "Логин");
            activity.onStart();
            if (args[0].equals("initial")) {
                check(initial == field(activity, "Логин"), "Initial onStart replaced visible input");
            } else if (args[0].equals("updates")) {
                List<View> views = flatten(activity.getWindow().getDecorView());
                View entry = null;
                for (View view : views) if (view instanceof android.widget.TextView && "Обновления приложения".contentEquals(((android.widget.TextView)view).getText())) {
                    check(entry == null, "Duplicate updates entries"); entry = view;
                }
                check(entry != null, "Missing updates entry");
                check(views.indexOf(entry) > views.indexOf(submit(activity)), "Updates entry appears before login submission");
                entry.performClick();
                check(activity.lastIntent != null && activity.lastIntent.destination == UpdatesActivity.class, "Updates click does not open UpdatesActivity");
                foreground(activity);
                check(initial == field(activity, "Логин"), "Return from updates replaced form");
            } else {
                EditText username = field(activity, "Логин");
                EditText password = field(activity, "Пароль");
                EditText totp = field(activity, "Код TOTP");
                username.setText("  Synthetic User  ");
                if (args[0].equals("keepass")) {
                    foreground(activity);
                    check(username == field(activity, "Логин"), "KeePass return replaced the username input");
                    check("  Synthetic User  ".contentEquals(username.getText()), "KeePass return erased exact username");
                    password.setText(" synthetic-password-fixture ");
                    password.requestFocus(); password.setSelection(2, 5);
                    foreground(activity);
                    check(password == field(activity, "Пароль"), "KeePass return replaced the password input");
                    check("  Synthetic User  ".contentEquals(username.getText()), "Second return erased username");
                    check(" synthetic-password-fixture ".contentEquals(password.getText()), "Second return erased password");
                    check(password.hasFocus() && password.getSelectionStart() == 2 && password.getSelectionEnd() == 5, "Return changed focus/selection");
                    totp.setText("123456");
                    foreground(activity);
                    check(totp == field(activity, "Код TOTP"), "Background return replaced TOTP input");
                    check("123456".contentEquals(totp.getText()), "Background return erased TOTP");
                } else {
                    password.setText("synthetic-password-fixture"); totp.setText("123456");
                    if (args[0].equals("submit")) {
                        submit(activity).performClick();
                        check(password.getText().length() == 0, "Submission retained password in held input");
                        check(totp.getText().length() == 0, "Submission retained TOTP in held input");
                    } else {
                        reset(activity);
                        check(field(activity,"Логин").getText().length() == 0, "Reset retained username");
                        check(field(activity,"Пароль").getText().length() == 0, "Reset retained password");
                        check(field(activity,"Код TOTP").getText().length() == 0, "Reset retained TOTP");
                    }
                }
            }
            System.out.println("PASS host contract " + args[0]);
        } finally { activity.onStop(); activity.onDestroy(); }
    }
}
