[app]

# PTv Android Cloud Control client
title = PTv
package.name = ptv
package.domain = com.ptv.cloud
source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,json,atlas
version = 1.0.0
requirements = python3,kivy==2.3.0,requests,certifi,urllib3,idna,charset-normalizer
orientation = portrait
fullscreen = 0

android.api = 35
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True
android.enable_androidx = True
android.permissions = android.permission.INTERNET,android.permission.ACCESS_NETWORK_STATE
android.allow_backup = True

p4a.bootstrap = sdl2
log_level = 2
warn_on_root = 1
