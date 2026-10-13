# INV-WATT-09 blind Android chooser host

`test_control_android_attachment_chooser_host_blind.py` compiles the real
`MainActivity.java` without reading it and exercises the installed public
`WebChromeClient.onShowFileChooser` callback on the existing synthetic native
login/background host. Tests never inspect private Activity fields.

The recording host supports both `startActivityForResult`/`onActivityResult` and
`ActivityResultLauncher<Intent>`, so the contract does not select an implementation
API. Android SDK method signatures and URI/Intent/ClipData shapes are represented
by narrow host doubles; the production Activity remains the subject under test.

Cases cover single/multiple content URIs, OPEN_DOCUMENT/OPENABLE intent,
exactly-once cancel/result/replacement/destroy, provider launch/result failures,
background return retaining the pending callback, stale login navigation,
foreign WebView/origin, non-content URIs and no broad storage permissions.
Normal chooser flows also guard native auth calls, credential clears and cookie
removal. An existing background ACK case runs with these new host doubles to
check fixture compatibility.

Baseline `ec6f538`: compilation PASS; 14 cases run, 10 semantic RED and 4 PASS.
Nine positive chooser cases fail because the public callback does not accept the
own authenticated page; unavailable-provider handling also fails to complete its
callback. These are runtime assertions, not missing SDK methods or compiler errors.
Existing background host suite: 13 PASS.

This is not device/provider UI, rotation-process recreation, APK update/signature
or persistent-login acceptance. Those require the signed candidate and device
smoke. No emulator/device or APK build is used here.
