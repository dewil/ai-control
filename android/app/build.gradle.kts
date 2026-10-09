plugins { alias(libs.plugins.android.application) }
android {
    namespace = "ru.dewil.aicontrol"
    compileSdk = 36
    buildToolsVersion = "36.0.0"
    defaultConfig {
        applicationId = "ru.dewil.aicontrol"
        minSdk = 26
        targetSdk = 36
        versionCode = 8
        versionName = "0.1.7"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    buildFeatures { buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    val signingFile = System.getenv("AI_CONTROL_ANDROID_KEYSTORE")
    signingConfigs {
        if (!signingFile.isNullOrBlank()) create("release") {
            storeFile = file(signingFile)
            storePassword = System.getenv("AI_CONTROL_ANDROID_STORE_PASSWORD")
            keyAlias = System.getenv("AI_CONTROL_ANDROID_KEY_ALIAS")
            keyPassword = System.getenv("AI_CONTROL_ANDROID_KEY_PASSWORD")
        }
    }
    buildTypes {
        debug { applicationIdSuffix = ".debug" }
        release {
            isMinifyEnabled = false
            if (!signingFile.isNullOrBlank()) signingConfig = signingConfigs.getByName("release")
        }
    }
}
gradle.taskGraph.whenReady {
    if (allTasks.any { it.path.startsWith(":app:") && it.name.contains("Release") } &&
        listOf("AI_CONTROL_ANDROID_KEYSTORE", "AI_CONTROL_ANDROID_STORE_PASSWORD",
               "AI_CONTROL_ANDROID_KEY_ALIAS", "AI_CONTROL_ANDROID_KEY_PASSWORD").any { System.getenv(it).isNullOrBlank() }) {
        throw GradleException("Release requires AI_CONTROL_ANDROID signing environment")
    }
}
dependencies {
    implementation(project(":policy"))
    implementation(project(":updater"))
    implementation(libs.kotlinx.coroutines.android)
    implementation("androidx.activity:activity:1.11.0")
    testImplementation(libs.junit)
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
}
