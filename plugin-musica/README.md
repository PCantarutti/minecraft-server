# Plugin de música (Paper + Simple Voice Chat)

Toca música para todo mundo no servidor pelo Simple Voice Chat. Cliente só
precisa do Simple Voice Chat (Fabric `2.6.27+26.3`); nada de mod próprio.

- **YouTube** (busca, link, playlist): [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  baixa o áudio para `plugins/Musica/cache/` (apagado ao fim da faixa); o
  lavaplayer decodifica. Baixar pelo próprio yt-dlp porque o YouTube recusa
  (403) a URL do áudio aberta fora dele. Viola os termos do
  YouTube e quebra quando o YouTube muda algo: atualize o yt-dlp
  (`yt-dlp -U` ou `pip install -U yt-dlp`), não precisa recompilar.
- **SoundCloud e links diretos de áudio**: lavaplayer direto.
- Áudio sai como Opus mono 48 kHz num canal estático (sem posição) por jogador.

Por que não o `youtube-source` do lavaplayer: em nov/2026 todos os clientes
dele falhavam (assinatura, SABR, "requires login", "not a bot"), mesmo com
yt-cipher e OAuth.

## Comandos

| Comando | O quê |
|---|---|
| `/music play <url ou busca>` | Enfileira. Texto vira busca no YouTube. Leva ~5 s até tocar. |
| `/music playlist <url>` | Playlist do YouTube ou do Spotify. |
| `/music queue` | Mostra a fila (no jogo abre a tela da fila). |
| `/music next <n>` | A n-ésima da fila passa a tocar a seguir. |
| `/music shuffle` | Aleatoriza a fila. |
| `/music pause` | Pausa / continua (alterna). |
| `/music skip` / `/music stop` | Pula / limpa fila e para. |
| `/music volume <0-100>` | Volume para todos. Cada jogador também ajusta "Música" no menu do voice chat (V). |

Spotify (`play` ou `playlist`): só os nomes das faixas são lidos (Web API) e
cada faixa é buscada no YouTube na hora de tocar. Precisa de
`spotify.client-id`/`client-secret` em `plugins/Musica/config.yml` (app em
https://developer.spotify.com/dashboard).

## Player, playlists e barra "tocando agora"

- Barra no topo da tela de todos com a música atual e o tempo (⏸ quando pausada).
- **Player** (`/music`, tecla **Ações rápidas** ou **Opções personalizadas** no menu de pausa):
  capa, título, progresso, próxima da fila; ↺ ⏸ » ⤨ ■; busca com escolha da versão
  (prévia com capa), volume, fila e playlists.
- **Playlists** salvas no servidor, compartilhadas por todos, em `plugins/Musica/biblioteca.json`
  (no volume `mc_data`, sobrevive a rebuild). ♥ Salvar no player, na prévia ou a fila inteira;
  tocar tudo/aleatório, remover faixas, apagar.
- O lançador vem do datapack `datapack/musica`, que a imagem copia para o mundo ativo (`DATAPACKS`).
  Sem mod: as telas são dialogs do próprio jogo.

## Requisitos no servidor

No Docker do projeto já vem tudo (`Dockerfile` nesta pasta; veja a Fase 10 do
[SETUP.md](../SETUP.md)). Fora dele:

- `voicechat-bukkit-2.6.27.jar` em `plugins/`.
- `yt-dlp` + um runtime JS (deno, o padrão do yt-dlp; ou node com
  `--js-runtimes node`). Comando configurável em `ytdlp.command` no
  `config.yml`.
- Porta **UDP 24454** (voice chat) exposta.

## Build

```bash
./gradlew build
```

Gradle baixa sozinho o JDK 25. Jar: `build/libs/musica-1.0.0.jar`.
