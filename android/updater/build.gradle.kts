plugins {
    alias(libs.plugins.android.library)
}

android {
    namespace = "ru.dewil.aicontrol.updater"
    compileSdk = 36

    defaultConfig {
        minSdk = 26
        buildConfigField("String", "UPDATE_MANIFEST_URL", "\"https://llm-web.dewil.ru:18443/download/android/version.json\"")
        buildConfigField("String", "UPDATE_LANDING_URL", "\"https://llm-web.dewil.ru:18443/download/android/\"")
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation(project(":policy"))
    implementation(libs.core.ktx)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.serialization.json)

    testImplementation(libs.junit)
}
