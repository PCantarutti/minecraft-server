plugins {
    java
    id("com.gradleup.shadow") version "9.6.1"
}

group = "dev.pedro"
version = "1.0.0"

java { toolchain.languageVersion = JavaLanguageVersion.of(25) }

repositories {
    mavenCentral()
    maven("https://repo.papermc.io/repository/maven-public/")
    maven("https://maven.maxhenkel.de/repository/public")
    maven("https://maven.lavalink.dev/releases")
    maven("https://jitpack.io") // ponytail: transitive deps of lavaplayer
}

dependencies {
    compileOnly("io.papermc.paper:paper-api:26.3.build.244-stable")
    compileOnly("de.maxhenkel.voicechat:voicechat-api:2.6.27")
    implementation("dev.arbjerg:lavaplayer:2.2.7")
}

tasks.shadowJar {
    archiveClassifier = ""
    duplicatesStrategy = DuplicatesStrategy.INCLUDE
    mergeServiceFiles()
}
tasks.jar { archiveClassifier = "plain" }
tasks.build { dependsOn(tasks.shadowJar) }
