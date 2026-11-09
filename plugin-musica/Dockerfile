# Imagem do servidor = itzg/minecraft-server + plugin de música + plugin de lag
# (../plugin-lag) + yt-dlp + deno.
# Contexto: esta pasta (o compose aponta pra ela). Nada de bind mount: o painel
# roda `compose up` de dentro do container dele, onde os caminhos do host não
# existem.
ARG MC_JAVA=java25

# --- 1. Compila o plugin. Imagem com Gradle pronto (Docker Hub) em vez do wrapper: daqui o
# services.gradle.org responde 504 ao download do wrapper e derrubava o build. Cache das libs entre builds.
FROM gradle:jdk25 AS build
WORKDIR /src
COPY . .
RUN --mount=type=cache,target=/home/gradle/.gradle gradle --no-daemon -q shadowJar

# --- 1b. Plugin de lag (pasta irmã, vem pelo additional_contexts "lag" do compose)
FROM gradle:jdk25 AS build-lag
WORKDIR /src
COPY --from=lag . .
RUN --mount=type=cache,target=/home/gradle/.gradle gradle --no-daemon -q check jar

# --- 2. Servidor
FROM itzg/minecraft-server:${MC_JAVA}
# yt-dlp standalone (não precisa de Python) + deno (runtime JS que o yt-dlp
# exige p/ decifrar o YouTube). Dono uid 1000 = usuário do servidor, para o
# plugin conseguir rodar `yt-dlp -U` a cada boot.
RUN curl -fsSL -o /usr/local/bin/yt-dlp https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux \
 && chmod 755 /usr/local/bin/yt-dlp && chown 1000:1000 /usr/local/bin/yt-dlp \
 && curl -fsSL -o /tmp/deno.zip https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip \
 && unzip -q /tmp/deno.zip -d /usr/local/bin && rm /tmp/deno.zip \
 && yt-dlp --version && deno --version
# O itzg copia /plugins para /data/plugins a cada start.
COPY --from=build /src/build/libs/musica-1.0.0.jar /plugins/musica.jar
COPY --from=build-lag /src/build/libs/lag-1.0.0.jar /plugins/lag.jar
# Tela de controle (Ações rápidas / menu de pausa); o itzg copia para o mundo ativo a cada start (DATAPACKS no compose).
COPY datapack/musica /datapacks/musica
