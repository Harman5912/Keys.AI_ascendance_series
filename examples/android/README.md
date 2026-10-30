# TaskHive — Android application (Kotlin)

A Gradle Kotlin project you can open in Android Studio directly: one Activity,
ViewBinding, a `ListView` fed by a real `SQLiteOpenHelper` table, and an add /
toggle flow.

## Open it

1. Android Studio → **Open** → select `examples/android`.
2. Let Gradle sync (AGP 8.6.1, Kotlin 1.9.24, compileSdk 34, minSdk 24).
3. Run `app` on an emulator or device.

From the command line, if a JDK 17 + Android SDK are on this machine:

```bash
cd examples/android
gradle wrapper --gradle-version 8.7   # once, creates ./gradlew
./gradlew assembleDebug
```

## Status on this machine

`gradlew` and the Android SDK are **not** present here, so this project was
verified by file structure only — it has not been compiled. The README says so
rather than claiming a build that did not happen.

## Files

| File | Purpose |
| --- | --- |
| `settings.gradle.kts`, `build.gradle.kts`, `app/build.gradle.kts` | Gradle setup |
| `app/src/main/AndroidManifest.xml` | launcher activity |
| `.../MainActivity.kt` | UI wiring |
| `.../TaskDb.kt` | SQLite table, add/list/toggle |
| `app/src/main/res/` | layout, strings, theme |
