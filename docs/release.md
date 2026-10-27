# Releasing Digital Downloader

## One-time setup: Android signing key

Android only installs an update if it is signed with the **same key** as the installed version.
Create the key once, keep it safe, and store it in GitHub Secrets. **If you lose this key, existing
users must uninstall and reinstall.** Back it up somewhere private (password manager or offline drive).

```bash
keytool -genkeypair -v -keystore digitaldownloader-release.jks \
  -alias digitaldownloader -keyalg RSA -keysize 2048 -validity 10000
```

Choose strong passwords (do not reuse the old one that was in the repository history: treat it as public).

Encode and add four repository secrets (GitHub > Settings > Secrets and variables > Actions):

| Secret | Value |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | output of `base64 -w0 digitaldownloader-release.jks` (Windows: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("digitaldownloader-release.jks"))`) |
| `ANDROID_KEYSTORE_PASSWORD` | keystore password |
| `ANDROID_KEY_ALIAS` | `digitaldownloader` |
| `ANDROID_KEY_PASSWORD` | key password |

Never commit the `.jks` file (it is ignored by `.gitignore`).

## Publishing a release

1. Make sure `main` is green (tests pass).
2. Bump the version in `installer.iss` and `android/app/build.gradle` (`versionName`, and **increase `versionCode` by 1**).
3. Tag and push:

```bash
git tag v2.1.0
git push origin v2.1.0
```

The workflow tests, builds Windows / Android / Linux, signs the APK and publishes the GitHub Release.
A push to `main` alone builds and tests but does **not** publish a release.
A tag build fails on purpose if the signing secrets are missing, so an unsigned APK is never published.

## Versioning

Semantic versioning: `MAJOR.MINOR.PATCH`. Android `versionCode` is an integer that must grow with every release.
