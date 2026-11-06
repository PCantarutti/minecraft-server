# Minecraft ao lado da stack igenda

Projeto Docker **separado** (`name: minecraft`), rede própria, limites duros.
Não altera nada do `igenda-api/docker-compose.yml` nem do deploy.

**Passo a passo: [SETUP.md](SETUP.md).** Comece por lá.

## Painel de controle

Interface web em `http://<ip-da-tailnet>:8080` que opera as três pilhas da
máquina e a própria máquina: **Minecraft** (console, jogadores, mundos,
backups), **igenda** e **Supabase** (ligar, desligar, container a container,
com a ordem de dependência imposta) e o **Servidor** (o agendamento de desligar
e acordar o PC). Código em [panel/](panel/), documentado na Fase 8 do SETUP.md.

Decisões visuais duráveis ficam em [DESIGN.md](DESIGN.md); verdade de produto,
em [PRODUCT.md](PRODUCT.md).

Ele **controla** o container do Minecraft; não o substitui. É o que preserva as
proteções abaixo. Painéis prontos (Crafty, Pterodactyl) rodam o servidor por
conta própria e descartariam todas elas.

Checagem do painel (sem framework, roda em segundos):

```bash
cd panel && python test_panel.py
```

## As três defesas contra conflito

Tudo neste compose existe pra que, se faltar recurso, quem cai é o Minecraft.

**RAM** — `MC_MEM_LIMIT` é teto duro do cgroup e `oom_score_adj: 800` põe o
Minecraft como primeiro candidato do OOM killer. Sem isso o kernel escolhe a
vítima pelo tamanho, e o maior processo da máquina costuma ser o Postgres do
Supabase. Heap da JVM sempre 1 GB abaixo do limite do container — metaspace,
threads e off-heap ficam fora do heap.

**CPU** — `cpu_shares: 256` contra o default 1024 dos outros containers. Em
disputa, api/web/postgres ganham. O teto `cpus` só evita o Minecraft encostar a
máquina durante geração de chunk.

**Rede** — rede `mc` isolada. O Minecraft não alcança `kong` nem o Postgres. A
porta 25565 escuta só no IP da tailnet: fora dela o servidor não existe, e o
UFW segue com OpenSSH apenas.

## Operação rápida

```bash
cd ~/app/minecraft && docker compose logs -f --tail 100
```

Console de admin (`op`, `whitelist`, `tps`, `stop`):

```bash
docker exec -i minecraft rcon-cli
```

Resto da operação e troubleshooting: [SETUP.md](SETUP.md).

## Pulado de propósito

- Plugins, Geyser (cross-play Bedrock), pre-generate de chunks. Adicione quando
  precisar — `chunky` (pre-generate) é o que mais ajuda se o tick cair.
- Monitoramento. `docker stats` + `tps` no rcon respondem para dois jogadores.
- systemd direto no host. Container dá limite de memória e `oom_score_adj` de
  graça, que é justamente o que protege o Postgres.
