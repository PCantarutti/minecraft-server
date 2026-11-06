# Minecraft no servidor que já roda o igenda

**Servidor:** i7-4790 (4C/8T), 16 GB, Ubuntu, já rodando a stack igenda
(Supabase self-host + api-prod + web-prod + cloudflared + WARP).

Ubuntu, Docker, UFW, fail2ban, swap e limite de log **já estão configurados**
pelo deploy do igenda. Nada disso se repete aqui. O que falta é só o Minecraft.

**Regra que manda neste setup:** a stack igenda sempre vence. Toda escolha abaixo
existe pra que, se faltar recurso, quem cai é o Minecraft — nunca o Postgres.

Faça as fases em ordem. A Fase 1 e a Fase 2 decidem os números e a rota — não
pule pra Fase 4.

---

## Fase 1 — Medir a folga real

Os valores do `.env.example` são estimativa. Agora dá pra medir. Por SSH no
servidor:

```bash
free -h; echo "--- containers ---"; docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}'; echo "--- disco ---"; df -h /
```

Três coisas pra ler:

1. **`MemAvailable` (coluna `available` do `free -h`).** É quanto sobra de fato.
2. **Soma do `docker stats`.** Quanto a stack igenda come hoje.
3. **`Avail` do `df -h /`.** World de 2 players cresce devagar, mas o `backups/`
   do igenda divide o mesmo disco.

Decida o heap pelo `available`:

| `available` | `MC_HEAP` | `MC_MEM_LIMIT` |
|---|---|---|
| ≥ 8 GB | `3G` | `4G` |
| 6–8 GB | `2G` | `3G` |
| 4–6 GB | `1500M` | `2G` |
| < 4 GB | **pare** | mede de novo com a stack em uso real |

Heap sempre **1 GB abaixo** do limite do container — a JVM usa metaspace,
threads e off-heap fora do heap. Heap igual ao limite do cgroup = OOM kill na
primeira GC pesada.

### Medido nesta máquina em 2026-11-05

```
Mem:  15Gi total | 2.5Gi used | 12Gi available     Swap: 4.0Gi (0B usado)
Soma dos 14 containers (igenda + supabase): ~2,2 GB
Disco /: 176G livres de 226G (18% usado)
```

Folga grande. **Os defaults do `.env.example` valem: `MC_HEAP=3G`,
`MC_MEM_LIMIT=4G`.** Sobram ~8 GB livres depois do Minecraft — bastante page
cache pro Postgres.

Pode subir mais? Pode, mas não ganha nada: dois jogadores não enchem 3 GB de
heap, e heap maior só aumenta a pausa de GC. Disco também não é problema — 176 GB
para um world que vai crescer alguns GB por ano.

Só vale remedir se a stack igenda crescer (mais tenants, Baileys com muitas
sessões) ou se o Supabase passar a ter volume de dados sério.

Não encha os 16 GB. O que sobra vira page cache do Postgres, e é isso que
mantém a api do igenda rápida.

Pouco espaço em disco? Isso é mais urgente que o Minecraft:

```bash
docker system df
```

```bash
docker image prune -a -f
```

---

## Fase 2 — WARP vs Tailscale

**Resolvido em 2026-11-05: Tailscale funciona, depois de uma exclusão no
split tunnel do WARP.** Se o servidor já está pareado na tailnet, pule para a
Fase 4. O diagnóstico fica registrado porque qualquer VPN nesta máquina vai
esbarrar na mesma coisa.

### O problema

`sudo tailscale up` ficava pendurado sem imprimir link. No `journalctl -u tailscaled`:

```
control: bootstrapDNS("derp10.tailscale.com", "137.220.36.168") ... context deadline exceeded
Received error: fetch control key: Get "https://controlplane.tailscale.com/key?v=148":
  dial tcp 192.200.0.104:443: connect: connection timed out
```

Falhava em IPv4 e IPv6, contra hostname e contra IP cru. Mas ao mesmo tempo o
`curl` para os **mesmos hosts** respondia 200 em menos de 1s. Ou seja: não era
DNS, não era bloqueio de categoria no Gateway, não era a rede.

### A causa

O WARP instala uma tabela nftables própria:

```
table inet cloudflare-warp
  chain output { type filter hook output priority filter; policy drop; }
```

**Policy drop.** Só passam `lo`, a interface `CloudflareWARP`, DHCP, ICMP e o
endpoint do WARP. Tudo mais que tente sair pela placa física morre ali — é a
proteção anti-leak (`Firewall Scope: All interfaces`).

E o `tailscaled` sai justamente pela placa física: ele marca os próprios pacotes
com `fwmark 0x80000` (pra não criar loop com a própria `tailscale0`) e instala
`ip rule` de prioridade 5210 mandando o marcado pra tabela `main`, que roteia
via `enp2s0`. Rota válida, firewall fecha.

O `curl` passa porque sai sem marca, cai na regra 32765 do WARP e entra no túnel.

### O conserto

Excluir o Tailscale do túnel faz o WARP escrever `accept` naquela chain. É a via
oficial, não gambiarra.

Zero Trust → **Team & Resources → Devices → Device profiles → General profiles**
→ profile **Default** → aba **Split tunnels** → **Add split tunnel entries**:

| Type | Value |
|---|---|
| Domain | `tailscale.com` |

Só isso. Uma entrada.

- **Não** troque o modo (`Exclude IPs and domains`): trocar zera a lista inteira,
  inclusive `192.168.0.0/16` (seu SSH) e `100.64.0.0/10` (a faixa da tailnet).
- **Não** clique em `Restore default entries` — apaga a entrada nova.
- Não existe entrada por porta: split tunnel só aceita IP/CIDR ou domínio. O
  tráfego direto entre peers já está coberto por `100.64.0.0/10`, que é default.
- Editar o profile Default é seguro aqui porque a org tem **1 device** enrolado.
  Com mais devices, crie um profile separado (exige plano pago).

Salvar reinicia o cliente WARP: alguns segundos sem rede, e o `cloudflared` pode
piscar junto.

### Lição

A config do WARP não prevê isso. O teste que decide é comparar o daemon com um
`curl` pro mesmo host: curl passa e daemon não, é firewall de interface.

---

## Fase 3-A — Tailscale

Pré-requisito: a exclusão de `tailscale.com` da Fase 2 já aplicada. Sem ela, o
`tailscale up` fica pendurado para sempre.

```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

`--accept-dns=false` é obrigatório: sem ele o Tailscale reescreve o
`/etc/resolv.conf` e briga com o DNS over HTTPS do WARP, o que derruba a
resolução de nomes do servidor inteiro — e com ela o `cloudflared`. Você conecta
pelo IP da tailnet, então MagicDNS não faz falta.

`--timeout` evita pendurar o terminal se algo estiver errado:

```bash
sudo tailscale up --accept-dns=false --timeout=30s
```

Imprimiu `To authenticate, visit: https://login.tailscale.com/a/...`? Abra no
navegador do seu PC e logue. O `timeout waiting for Tailscale service` que
aparece depois é só o flag de 30s estourando enquanto você autenticava — não é
erro.

Ficou pendurado **sem** imprimir link = a Fase 2 não foi aplicada.

```bash
tailscale ip -4
```

Anote o `100.x.y.z`. É o endereço do servidor, fixo pra sempre.

### Medido nesta máquina

```
tailnet: 100.95.171.109      WARP: 100.96.0.1
```

Faixas próximas mas distintas — sem colisão. Se um dia o Tailscale entregar um
IP que bata com o do WARP, force outro em Machines → o servidor → Edit IP.

### Checagem de sanidade

```bash
tailscale status; docker ps --filter name=igenda --format '{{.Names}}	{{.Status}}'; warp-cli status; getent hosts api.mercadopago.com
```

Tudo precisa responder: tailnet conectada, containers `healthy`, WARP
`Connected`, DNS resolvendo. Qualquer um ruim → `sudo tailscale down` reverte na
hora.

### Nos dois PCs

Instale de <https://tailscale.com/download> e logue na mesma conta. Sem
compartilhar conta: convide o device dela em
<https://login.tailscale.com/admin/machines> → Share.

Depois que ambos estiverem na tailnet:

```bash
tailscale status
```

`direct` = WireGuard ponta a ponta. `relay "xxx"` = via DERP, porque o WARP
media o UDP. Funciona igual, com uns 20-40 ms a mais — para dois jogadores,
irrelevante.

Siga pra Fase 4 com `MC_BIND=` o IP da tailnet.

---

## Fase 3-B — playit.gg — **plano B, não usado**

A Fase 3-A resolveu, então isto aqui não é necessário. Fica documentado para o
caso de a política do WARP mudar e a exclusão da Fase 2 deixar de valer.

Cliente TCP comum sobre HTTPS: sem interface tun, sem fwmark, sem tocar em
tabela de rota — mesmo perfil do `cloudflared`. Passa onde uma VPN não passa.

A diferença que importa: o endereço do playit é **público**. Qualquer um que o
descubra entra. Com Tailscale, só quem está na tailnet enxerga o servidor. Se um
dia precisar cair pra cá, a whitelist da Fase 7 deixa de ser opcional.

UFW segue só com OpenSSH. Nenhuma porta aberta. O IP real do servidor continua
escondido atrás do Cloudflare.

Suba o agente:

```bash
docker run -d --name playit --restart unless-stopped --network host ghcr.io/playit-cloud/playit-agent:latest
```

Pegue o link de pareamento:

```bash
docker logs playit 2>&1 | grep -i "visit\|claim\|http"
```

Sai algo como `https://playit.gg/claim/<código>`. Abra no navegador do seu PC,
crie a conta (ou logue) e confirme o agente.

No painel, **Tunnels → Add Tunnel**:

| Campo | Valor |
|---|---|
| Tipo | **Minecraft Java** (ou TCP genérico na 25565) |
| Local address | `127.0.0.1` |
| Local port | `25565` |

Ele devolve um endereço tipo `algumacoisa.gl.joinmc.link`. **É esse que vocês
dois usam no cliente do Minecraft** — anote.

Confirme que o agente ficou de pé e que o igenda não sentiu nada:

```bash
docker logs playit --tail 20; docker ps --filter name=igenda --format '{{.Names}}\t{{.Status}}'
```

> `--network host` é necessário: o agente precisa alcançar `127.0.0.1:25565` do
> host, que é onde o Minecraft vai escutar. Ele não entra em nenhuma rede Docker
> do igenda nem do Minecraft.

Como o endereço é público, **ligue a whitelist** assim que entrarem (Fase 7).
Sem ela, qualquer um que descubra o endereço entra no mundo de vocês.

Neste caminho o `MC_BIND` seria `127.0.0.1`, e não o IP da tailnet.

---

## Fase 4 — Copiar os arquivos

Do **seu PC Windows**, no PowerShell:

```powershell
ssh pedro@IP_DO_SERVIDOR "mkdir -p ~/app/minecraft"
```

```powershell
scp "C:\Projetos\servidor-minecraft\docker-compose.yml" "C:\Projetos\servidor-minecraft\.env.example" "C:\Projetos\servidor-minecraft\README.md" "C:\Projetos\servidor-minecraft\SETUP.md" pedro@192.168.1.50:~/app/minecraft/
```

`~/app/minecraft` fica **ao lado** de `~/app/igenda-api`, não dentro. Projeto
Docker separado (`name: minecraft`), rede própria, nada compartilhado.

---

## Fase 5 — Configurar

```bash
cd ~/app/minecraft && cp .env.example .env && nano .env
```

Quatro linhas:

- `MC_BIND=` — `100.x.y.z` (Fase 3-A) ou `127.0.0.1` (Fase 3-B).
- `MC_HEAP=` e `MC_MEM_LIMIT=` — da tabela da Fase 1.
- `MC_OPS=SeuNick,NickDaNamorada` — nicks do Minecraft, maiúsculas exatas.

Confere o que o compose resolveu:

```bash
docker compose config | grep -E "MEMORY|memory:|cpus:|25565|oom"
```

Precisa aparecer o `memory` do limite, `cpu` com teto e `oom_score_adj: 800`.
Sem o `oom_score_adj`, o kernel escolhe a vítima pelo tamanho — e aí mata o
Postgres.

---

## Fase 6 — Subir

```bash
cd ~/app/minecraft && docker compose up -d && docker compose logs -f
```

Primeiro boot baixa o Paper e gera o world: **2 a 5 minutos**. Espera a linha:

```
Done (NNs)! For help, type "help"
```

`Ctrl+C` sai do log, não para o servidor.

```bash
docker compose ps
```

`healthy` = pronto. Antes de 180s, `starting` é normal (`start_period` do
healthcheck).

Agora o teste que importa — a stack igenda sob pressão:

```bash
free -h; docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}'
```

`available` abaixo de 1,5 GB? Baixa o `MC_HEAP` em 1 G, `docker compose up -d`, e
mede de novo.

---

## Fase 7 — Entrar

Tailscale ligado nos dois PCs. Minecraft **Java Edition** → Multiplayer →
Add Server → Server Address:

```
100.95.171.109:25565
```

(O IP da tailnet do servidor, de `tailscale ip -4`.)

Sem Tailscale ligado não conecta — e é esse o ponto: o servidor não existe para
quem está fora da tailnet.

Console de admin:

```bash
docker exec -i minecraft rcon-cli
```

Útil lá dentro: `op SeuNick`, `tps` (tick rate), `list`, `stop`. `Ctrl+D` sai.

### Whitelist: opcional aqui

Na tailnet só entra quem você convidou, então a whitelist é redundante. Se
quiser a camada extra mesmo assim:

```
whitelist add SeuNick
whitelist add NickDaNamorada
whitelist on
```

Ela passa a ser **obrigatória** se um dia o servidor migrar pro playit
(Fase 3-B), onde o endereço é público.

---

## Fase 8 — Painel de controle

Interface web na tailnet que opera as **três pilhas da máquina e a própria
máquina**: Minecraft, igenda, Supabase e o Servidor.

O painel **controla** o container do Minecraft em vez de substituí-lo. Isso não
é detalhe: os limites de cgroup, o `cpu_shares` e o `oom_score_adj` do compose
são o que impede o Minecraft de derrubar o Postgres do igenda. Um painel que
rodasse o servidor por conta própria (Crafty, Pterodactyl) jogaria isso fora.

### Subir

```bash
cd ~/app/minecraft && docker compose -f painel-compose.yml up -d --build
```

O painel tem **projeto Docker próprio** (`painel`), separado do `minecraft`. Não
é cosmético: dentro do projeto do Minecraft, tirar o Minecraft do boot levaria o
painel junto, e a máquina acordaria sem nada que religasse o resto pela web.

Os volumes continuam com os nomes antigos (`minecraft_mc_data`,
`minecraft_panel_data`), declarados como externos — volume nomeado é escopado
por projeto, e renomear teria apagado senha, agendamento e configuração.

A senha inicial é aleatória e aparece **uma única vez** no log:

```bash
docker compose -f painel-compose.yml logs painel | grep senha
```

Anote e troque na aba Configuração. Não existe senha padrão de propósito: o
painel tem o socket do Docker montado, e credencial conhecida nele seria root
nesta máquina.

### Acessar

<http://100.95.171.109:8080> — o IP da tailnet, com Tailscale ligado.

`PANEL_BIND` no `.env` é a mesma regra da porta do jogo: nunca `0.0.0.0`.

### O que cada aba faz

A barra lateral lista os quatro alvos com ponto de estado, busca, e
**Ligar tudo / Desligar tudo** (que respeitam a ordem de dependência). Clicar
troca o conteúdo à direita. O cabeçalho sempre traz nome, estado e
Ligar/Reiniciar/Desligar.

**Minecraft**

| Aba | O quê |
|---|---|
| Visão geral | Estado, memória, CPU, mundo ativo, quem está jogando, backups recentes |
| Console | Log ao vivo e qualquer comando RCON (`tps`, `gamerule`, `time set`…) |
| Jogadores | Lista de quem está online com o rosto da skin, OP, whitelist, kick, ban |
| Conteúdo | Mundos: **criar**, ativar, baixar, apagar, enviar `.zip` do seu PC, e navegador de arquivos |
| Automação | Agendamento do servidor e backups, com envio pro Drive |
| Configurações | Ícone do servidor, opções em lista, senha do painel |

**igenda e Supabase**

| Aba | O quê |
|---|---|
| Visão geral | Quantos containers no ar, classe de risco, e quem depende de quem |
| Containers | Ligar, reiniciar e parar container por container |
| Log | `docker logs` de qualquer container da pilha |

O painel **impõe a ordem de dependência**: ligar o igenda sobe o Supabase antes;
desligar o Supabase desce o igenda primeiro. Controle por label do compose — os
repositórios dessas pilhas não precisam estar montados no painel.

**Servidor** (a máquina)

| Aba | O quê |
|---|---|
| Visão geral | Hostname, uptime, memória, disco, carga, e as três pilhas num lugar |
| Tarefas | Gerenciador de tarefas: RAM e CPU da máquina e **de cada container**, agrupado por pilha |
| Energia | O agendamento de desligar/acordar: ligar, desligar, horários, pular uma noite |
| Histórico | Tudo que o painel fez, por você ou pelo agendador |

A aba **Tarefas** normaliza o CPU para a máquina inteira — o `docker stats` mede
sobre um núcleo só, então 320% lá vira 40% aqui, com 8 threads. A memória de cada
container aparece contra o **teto dele**, não contra a máquina: o Minecraft perto
de 100% é a JVM ocupando o heap reservado, não falta de RAM.

### Subir sozinho no boot

A máquina acorda às 07:00 todo dia. Na **Visão geral** de cada pilha há um
botão para tirá-la do boot — útil quando você vai usar o servidor só para o
Minecraft, ou só para o igenda, e não quer a outra pilha consumindo recursos.

Isso grava a política de restart do Docker direto nos containers
(`unless-stopped` ou `no`). Um `docker compose up -d` feito por fora volta ao
que estiver no arquivo do projeto.

Se tirar o igenda do boot, tire o Supabase também — senão a pilha acorda sem
banco.

### Energia: como funciona

O host desliga por `rtcwake` e acorda pelo despertador da placa-mãe. O painel
lê e mexe nisso entrando nos namespaces do PID 1 pelo socket do Docker
(`nsenter -t 1`) — sem agente instalado no host e sem regra de sudo.

- **Ligar/desligar** faz `systemctl enable|disable --now` no timer.
- **Horários** reescrevem o `OnCalendar` do unit (dormir) e o `tomorrow HH:MM`
  do script (acordar).
- **Pular esta noite** dá `systemctl stop` sem desabilitar: o timer voltaria
  sozinho no próximo boot, e como pular a noite significa que não vai haver
  boot, o agendador do painel religa quando o dia virar. É o que usar quando a
  noite vai virar, em vez de desligar o agendamento e esquecer de religar.
- **Desligar agora** roda o mesmo script do agendamento: cai tudo e a máquina
  volta sozinha no horário de acordar.

O relógio do sistema está em UTC e o painel em America/Sao_Paulo — os horários
na interface são sempre de São Paulo, já convertidos.

### Ícone e opções

O **ícone** é a imagem ao lado do nome na lista de servidores do cliente. Envie
qualquer PNG, JPG ou WebP: o painel recorta no centro e reduz para 64×64, que é
o único formato que o Minecraft aceita — fora disso ele ignora sem avisar. Só
aparece depois de reiniciar o servidor.

As **opções de configuração** são listas, não texto livre: dificuldade, modo de
jogo, PvP, versão, Java, memória e CPU vêm com os valores válidos, e o mundo
ativo lista os mundos que existem de fato.

A lista também vale no servidor, não só na tela: um POST forjado com
`MC_GAMEMODE=deus` ou `MC_BIND=0.0.0.0; curl evil` é recusado antes de encostar
no `.env`. Há ainda uma trava para a armadilha clássica — memória da JVM igual
ou acima do limite do container, que mata o processo na primeira coleta de lixo
pesada.

### Google Drive

O login do Google abre navegador e não roda dentro do container. No **seu PC**:

```bash
rclone config
```

Crie um remote do tipo `drive`. Depois envie o `rclone.conf` gerado pela aba
Backups e preencha o destino (ex.: `gdrive:minecraft`). O botão "Testar destino"
confirma antes de você depender dele.

### Criar um mundo pelo painel

Quem gera é o servidor, no boot seguinte — o painel só escreve os parâmetros e
recria o container. É como o jogo faz.

**Geração** (só vale na criação; depois ficam gravados no `level.dat`):
semente, tipo de mundo (normal, plano, biomas grandes, amplificado, bioma
único), gerar estruturas, raio máximo do mundo.

**Regras do jogo** (valem para o servidor inteiro, não por mundo — o
`server.properties` é único): dificuldade, modo de jogo, hardcore, forçar modo
ao entrar, PvP, Nether, voo, monstros, animais, aldeões, blocos de comando e
proteção do spawn.

Dois cuidados embutidos:

- **Hardcore força dificuldade `hard`.** O painel já ajusta ao salvar, em vez
  de você descobrir pela dificuldade "errada" dentro do jogo.
- **A semente é sempre reescrita**, mesmo em branco. Sem isso a semente de um
  mundo vazaria para o próximo que você criasse sem informar uma.

Os nomes de variável vêm de `/image/property-definitions.json` da própria
imagem itzg, não de memória.

### Mundos grandes

Testado com um mundo criativo real: **zip de 1,8 GB, 2,0 GB descompactado,
enviado em 50 segundos** pela tailnet (os dois PCs na mesma LAN).

Upload e download passam por arquivo em disco, nunca pela memória — o container
tem 512 MB de RAM e 170 GB de disco livre, então o gargalo certo é o disco.
O `TMPDIR` do painel aponta para o próprio volume para o buffer do upload não
inchar a camada do container.

O download sai em ZIP sem compressão: região de mundo já vem comprimida, e
deflate gastaria minutos de CPU — disputada com o servidor — para economizar
quase nada.

### Atualização automática

As regiões só-leitura se recarregam sozinhas, sem você apertar F5: lateral a
cada 6 s, cabeçalho a cada 8 s, quem está online a cada 8 s, visão geral a cada
10 s, Tarefas a cada 5 s. Entrar no servidor pelo jogo aparece na aba Jogadores
em até 8 segundos.

Formulários ficam **fora** das regiões que se recarregam: campo de horário, nick
e a tela de Configurações não são atualizados sozinhos, senão apagariam o que
você está digitando.

Os rostos das skins vêm do `mc-heads.net` e são buscados pelo **seu navegador** —
o nick sai do seu PC para esse serviço, o servidor não participa.

### Operações longas

Backup e restauração rodam em segundo plano e mostram **porcentagem** — na tela
e no log do painel (`docker compose -f painel-compose.yml logs -f painel`). A
requisição volta na hora em vez de segurar o navegador por 80 segundos.

A porcentagem é estimada pelo tamanho que já saiu contra o tamanho esperado; o
`tar` não reporta progresso. Erra alguns pontos no fim, mas responde a pergunta
que importa: está andando ou travou.

### Quando o Minecraft está mesmo no ar

O painel só diz "no ar" depois da linha `Done (Xs)! For help, type "help"` no
log — antes disso mostra **subindo**. Container rodando não é servidor pronto:
há uns 30 segundos entre uma coisa e outra, e dizer "no ar" ali é mentira.

O filtro usa `--since` com o horário de início do container, senão um `Done` da
execução anterior daria pronto na hora (o log sobrevive a restart).

### Ruído de RCON no console

O painel mantém **uma conexão RCON viva** em vez de abrir e fechar a cada
consulta. Cada abertura fazia o Paper escrever três linhas no console (o
"Thread RCON Client", o prompt `>....` e o "shutting down") — com o painel
consultando a cada poucos segundos, isso enterrava o log do jogo. Medido: 17
conexões por minuto antes, **zero depois**.

A exibição ainda limpa o que ficou no histórico: escapes de terminal e o prompt
do Paper. O prompt às vezes vem colado numa mensagem real, então o prefixo é
removido em vez de a linha ser descartada — e o eco de comando (`> say oi`)
sobrevive inteiro, porque é log de verdade.

### Confirmação digitada

Desligar ou reiniciar produção (igenda, Supabase), "Desligar tudo" e desligar a
máquina exigem **digitar o nome** para confirmar, não só clicar em OK. Um Enter
distraído num `confirm` derrubava produção; digitar é o degrau entre "quase
cliquei" e "eu quis". O Minecraft segue com confirmação simples.

### Limites conhecidos

- **Socket do Docker montado** = o painel é root nesta máquina. Por isso fica só
  na tailnet, com senha. Se um dia precisar expor além disso, troque por um
  proxy de socket restrito antes.
- **Servidor WSGI:** waitress, não o servidor de desenvolvimento do Flask. A
  troca foi necessária, não cosmética: o dev server engasgava transferindo
  gigabytes enquanto atendia o polling do painel, e era isso que fazia o
  download de backup de 2,3 GB falhar no navegador. Agora sai a ~17 MB/s.
- **Um usuário só**, sem papéis. Contas separadas só fariam sentido com mais
  gente administrando.
- **Backups ficam como `root`** em `backups/` (o painel roda como root). Apagar
  pela interface funciona; na mão, precisa de `sudo`.

---

## Fase 9 — Backup

O painel já faz isto pela aba Backups, que é o caminho recomendado — tem
retenção, restauração e envio pro Drive. O cron abaixo serve se você preferir
não depender do painel, ou como segunda rede de proteção.

Cron diário às 4h, 7 dias de retenção. Horário diferente do backup do igenda, pra
não disputar I/O:

```bash
mkdir -p ~/backups
```

```bash
(crontab -l 2>/dev/null; echo "0 4 * * * docker run --rm -v minecraft_mc_data:/d -v $HOME/backups:/b alpine tar czf /b/mc-\$(date +\\%F).tgz -C /d . && find $HOME/backups -name 'mc-*.tgz' -mtime +7 -delete") | crontab -
```

```bash
crontab -l | tail -2
```

Testa agora, não no dia que precisar:

```bash
docker run --rm -v minecraft_mc_data:/d -v $HOME/backups:/b alpine tar czf /b/mc-teste.tgz -C /d . && ls -lh ~/backups
```

---

## Operação

| O quê | Comando |
|---|---|
| Parar | `docker compose stop` |
| Subir | `docker compose up -d` |
| Log | `docker compose logs -f --tail 100` |
| Console | `docker exec -i minecraft rcon-cli` |
| RAM/CPU | `docker stats --no-stream` |
| Atualizar | `docker compose pull && docker compose up -d` |

Sobe sozinho no boot (`restart: unless-stopped`).

**Deploy do igenda não é afetado.** `redeploy.sh` e o pipeline agem no projeto
`igenda`; o Minecraft é o projeto `minecraft`. `docker compose down` num não
toca no outro.

Mas cuidado com um comando: **`docker system prune -a` apaga a imagem do
Minecraft** (e qualquer imagem sem container rodando). O volume `minecraft_mc_data`
sobrevive — `prune -a` não remove volumes sem `--volumes`. Nunca use
`--volumes` nessa máquina: leva o world **e** a sessão do Baileys.

---

## Se der problema

**Não conecta** — nesta ordem: o Minecraft está de pé (`docker compose ps` →
`healthy`)? O agente está vivo (`docker logs playit --tail 20`)? O túnel no
painel do playit aponta pra `127.0.0.1:25565`? Mudou o `.env` →
`docker compose up -d` pra aplicar.

Teste se o servidor responde localmente, isolando o playit do Minecraft:

```bash
docker exec -i minecraft rcon-cli list
```

Responde = Minecraft ok, problema é o túnel. Não responde = problema é o
Minecraft, veja os logs.

**Conecta e cai na hora** — whitelist ligada sem o nick dentro. `whitelist list`
no rcon.

**Servidor não sobe depois de enviar/restaurar mundo, log diz
`AccessDeniedException: ./<mundo>/session.lock`** — o mundo ficou com dono
errado. O painel roda como root e o servidor como uid 1000; arquivo criado por
um não é gravável pelo outro.

O painel já normaliza a posse no upload e no restore. Se aparecer mesmo assim
(mundo copiado na mão por `scp`, por exemplo):

```bash
docker exec painel python -c "import app; app.chown_like_data(app.MC_DATA)"
```

Backup antigo, feito antes dessa correção, guarda a posse errada dentro do
`.tgz` — por isso o restore normaliza depois de extrair, em vez de confiar no
arquivo.

**Relógio**: o host está em UTC, o painel e o servidor em America/Sao_Paulo. O
`date` por SSH mostra 3 horas a mais que os horários da aba Agendamento. Os
agendamentos seguem o fuso do painel, que é o que a interface mostra.

**Disco dos backups** — cada backup com o mundo criativo passa de 2 GB. Com
`keep=7` isso chega a ~15 GB. Confira com `df -h /` e baixe o `keep` se apertar.

**Container em loop de restart, log diz `requires running the server with Java
NN or above`** — a tag de Java da imagem ficou atrás da versão do Minecraft.
Aconteceu em 2026-11-05: `MC_VERSION=LATEST` trouxe o Minecraft 26.1, que exige
Java 25, com a imagem ainda em `java21`. Corrige no `.env`:

```bash
sed -i 's/^MC_JAVA=.*/MC_JAVA=javaNN/' .env && docker compose up -d
```

Trocando `NN` pelo número que o log pediu. Tags disponíveis em
<https://hub.docker.com/r/itzg/minecraft-server/tags>.

Esse acoplamento é consequência do `MC_VERSION=LATEST`: o Mojang sobe de JVM e a
imagem fixa não acompanha sozinha. Pinar `MC_VERSION` elimina a surpresa, ao
custo de atualizar na mão.

**Container em loop de restart, sem mensagem de Java** — `docker compose logs
--tail 50`. Confirma OOM:

```bash
docker inspect minecraft --format '{{.State.OOMKilled}} {{.State.ExitCode}}'
```

`true` = `MC_HEAP` alto demais pro `MC_MEM_LIMIT`. Heap 1 GB abaixo do limite.

**Lag** — `tps` no rcon-cli. Abaixo de 19, baixa `VIEW_DISTANCE` pra 8 e
`SIMULATION_DISTANCE` pra 6 no `docker-compose.yml`. Se o tick cai só quando o
igenda está em uso, abaixa `MC_CPUS`.

**Erro de subnet ao criar a rede** (`no available IPv4 addresses`) — o pool de
redes do Docker encheu. Lista e limpa as órfãs:

```bash
docker network ls && docker network prune -f
```

**Versão do cliente não casa** — pine no `.env` (ex.: `MC_VERSION=1.21.4`) e
`docker compose up -d --force-recreate`.

**igenda ficou lento depois do Minecraft** — `docker stats --no-stream`. Se o
`available` do `free -h` estiver apertado, o culpado é page cache perdido:
baixa `MC_HEAP`. `cpu_shares: 256` já garante que a api ganha CPU em disputa,
então lentidão quase sempre é RAM, não processador.
