package ru.dewil.aicontrol;

import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import java.util.ArrayList;
import java.util.List;

/** Independent oracle for INV-APP-09; real MainActivity, synthetic values only. */
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
    public static void main(String[] args) {
        MainActivity activity = new MainActivity();
        activity.onCreate(null);
        activity.onStart();
        EditText username = field(activity, "Логин");
        EditText password = field(activity, "Пароль");
        EditText totp = field(activity, "Код TOTP");
        username.setText("Synthetic User");
        foreground(activity);
        check(username == field(activity, "Логин"), "KeePass return replaced the username input");
        check("Synthetic User".contentEquals(username.getText()), "KeePass return erased username");
        password.setText("synthetic-password-fixture");
        foreground(activity);
        check(password == field(activity, "Пароль"), "KeePass return replaced the password input");
        check("Synthetic User".contentEquals(username.getText()), "Second return erased username");
        check("synthetic-password-fixture".contentEquals(password.getText()), "Second return erased password");
        totp.setText("123456");
        foreground(activity);
        check(totp == field(activity, "Код TOTP"), "Background return replaced TOTP input");
        check("123456".contentEquals(totp.getText()), "Background return erased TOTP");
        submit(activity).performClick();
        check(password.getText().length() == 0, "Submission retained password in held input");
        check(totp.getText().length() == 0, "Submission retained TOTP in held input");
        activity.onStop();
        activity.onDestroy();
        System.out.println("PASS INV-APP-09 same Activity keeps form; submission clears secrets");
    }
}
