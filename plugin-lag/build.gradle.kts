plugins { java }

group = "dev.pedro"
version = "1.0.0"

java { toolchain.languageVersion = JavaLanguageVersion.of(25) }

repositories {
    mavenCentral()
    maven("https://repo.papermc.io/repository/maven-public/")
}

dependencies {
    // Mesma versão do plugin-musica: os dois rodam no mesmo servidor.
    compileOnly("io.papermc.paper:paper-api:26.3.build.244-stable")
}

// Self-check sem framework: `./gradlew check` (e o build da imagem) roda o main.
val ruimCheck by tasks.registering(JavaExec::class) {
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass = "dev.pedro.lag.RuimCheck"
}
tasks.check { dependsOn(ruimCheck) }
// Sem JUnit: o self-check acima é o teste. Gradle 9 reprova `test` vazio.
tasks.test { enabled = false }
