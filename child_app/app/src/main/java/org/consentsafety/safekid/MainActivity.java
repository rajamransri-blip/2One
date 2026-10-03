package org.consentsafety.safekid;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

public class MainActivity extends Activity {
    private static final int PERMISSIONS = 12;
    private EditText server, email, password, pairing;
    private TextView status;
    private SharedPreferences prefs;
    private final int blue = Color.rgb(70, 150, 255);

    @Override public void onCreate(Bundle state) {
        super.onCreate(state); prefs = getSharedPreferences("safekid", MODE_PRIVATE);
        buildUi();
    }

    private TextView label(String text, int size) { TextView v = new TextView(this); v.setText(text); v.setTextColor(Color.rgb(230,238,255)); v.setTextSize(size); v.setPadding(8,10,8,6); return v; }
    private EditText input(String hint, String value, boolean secret) { EditText e = new EditText(this); e.setHint(hint); e.setHintTextColor(Color.rgb(145,161,189)); e.setTextColor(Color.WHITE); e.setSingleLine(true); e.setText(value); e.setPadding(12,8,12,8); if(secret) e.setInputType(0x81); return e; }
    private Button button(String text) { Button b = new Button(this); b.setText(text); b.setTextColor(Color.WHITE); b.setBackgroundColor(blue); b.setAllCaps(false); return b; }

    private void buildUi() {
        ScrollView scroll = new ScrollView(this); LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setPadding(22,18,22,24); root.setBackgroundColor(Color.rgb(8,12,22)); scroll.addView(root);
        TextView title = label("SafeKid\nVisible child safety app", 25); title.setTextColor(Color.WHITE); root.addView(title);
        TextView note = label("This app never hides monitoring. Location, camera, microphone and notifications are requested only after you tap a visible button.", 14); note.setTextColor(Color.rgb(145,161,189)); root.addView(note);
        server = input("Render server URL", prefs.getString("server", "https://twoones-l0s0.onrender.com"), false); root.addView(label("SERVER",12)); root.addView(server);
        email = input("Child account email", prefs.getString("email", ""), false); root.addView(label("CHILD ACCOUNT",12)); root.addView(email);
        password = input("Password", "", true); root.addView(password);
        Button login = button("Sign in to Render backend"); root.addView(login); login.setOnClickListener(v -> login());
        pairing = input("Parent pairing code", "", false); root.addView(label("PAIR DEVICE",12)); root.addView(pairing);
        Button claim = button("Accept pairing request"); root.addView(claim); claim.setOnClickListener(v -> claim());
        root.addView(label("Permissions (tap only when needed)",18));
        Button location = button("Enable visible location sharing"); root.addView(location); location.setOnClickListener(v -> ask(new String[]{Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION}));
        Button notification = button("Enable notifications"); root.addView(notification); notification.setOnClickListener(v -> { if (android.os.Build.VERSION.SDK_INT >= 33) ask(new String[]{Manifest.permission.POST_NOTIFICATIONS}); else message("Notifications are enabled by Android version."); });
        Button camera = button("Take photo (camera permission)"); root.addView(camera); camera.setOnClickListener(v -> ask(new String[]{Manifest.permission.CAMERA}));
        Button mic = button("Record voice (microphone permission)"); root.addView(mic); mic.setOnClickListener(v -> ask(new String[]{Manifest.permission.RECORD_AUDIO}));
        Button settings = button("Open Android app permissions"); root.addView(settings); settings.setOnClickListener(v -> startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + getPackageName()))));
        status = label("Checking device connection...",14); status.setTextColor(Color.rgb(49,210,138)); root.addView(status);
        setContentView(scroll); checkServer();
    }

    private void ask(String[] permissions) { requestPermissions(permissions, PERMISSIONS); }
    private void message(String text) { runOnUiThread(() -> status.setText(text)); }
    private String base() { return server.getText().toString().trim().replaceAll("/$", ""); }
    private void request(String method, String path, JSONObject payload, Callback callback) {
        new Thread(() -> { try {
            URL url = new URL(base() + path); HttpURLConnection c = (HttpURLConnection) url.openConnection(); c.setRequestMethod(method); c.setConnectTimeout(12000); c.setReadTimeout(15000); c.setRequestProperty("Content-Type", "application/json"); c.setRequestProperty("Accept", "application/json"); String token = prefs.getString("token", ""); if (!token.isEmpty()) c.setRequestProperty("Authorization", "Bearer " + token);
            if (payload != null) { c.setDoOutput(true); try(OutputStream out=c.getOutputStream()){out.write(payload.toString().getBytes(StandardCharsets.UTF_8));} }
            BufferedReader r = new BufferedReader(new InputStreamReader(c.getResponseCode() < 400 ? c.getInputStream() : c.getErrorStream())); StringBuilder s=new StringBuilder(); String line; while((line=r.readLine())!=null)s.append(line); callback.done(c.getResponseCode(), new JSONObject(s.toString())); c.disconnect();
        } catch(Exception e) { callback.done(0, new JSONObject()); message("Offline: " + e.getMessage()); } }).start();
    }
    private void checkServer() { request("GET", "/health", null, (code, data) -> message(code == 200 ? "● Render backend online" : "Backend returned " + code)); }
    private void login() { try { JSONObject p=new JSONObject(); p.put("email",email.getText().toString().trim()); p.put("password",password.getText().toString()); p.put("role","child"); request("POST","/auth/login",p,(code,d)->{ if(code==200){ prefs.edit().putString("token",d.optString("access_token")).putString("server",base()).putString("email",email.getText().toString().trim()).apply(); message("Signed in • child account connected"); } else message("Login failed: " + d.optString("detail","check account")); }); } catch(Exception e){message("Invalid login form");} }
    private void claim() { try { JSONObject p=new JSONObject(); p.put("code",pairing.getText().toString().trim()); p.put("device_name","SafeKid Android"); request("POST","/devices/pair",p,(code,r)->message(code==201?"Pairing accepted • parent connected":"Pairing failed: "+r.optString("detail","check code"))); } catch(Exception e){message("Enter the pairing code");} }
    private interface Callback { void done(int code, JSONObject data); }
}
