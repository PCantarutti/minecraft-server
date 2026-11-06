# PRODUCT.md

Console web que opera um servidor caseiro — um PC de mesa que roda, ao mesmo
tempo, um servidor de Minecraft para duas pessoas e a stack de produção de um
produto comercial.

## Platform

web

## Usuário e cena

Um usuário: Pedro, desenvolvedor, dono da máquina. Uma segunda pessoa (a
namorada) joga no servidor de Minecraft mas não opera o painel.

A cena real é doméstica, não um NOC: ele abre o painel do PC Windows, em casa,
normalmente à noite, para uma de três coisas — ligar o Minecraft para jogar,
conferir se o igenda continua de pé, ou mexer no horário em que a máquina se
desliga sozinha. Sessões curtas, às vezes às pressas antes de jogar. Não é uma
ferramenta que ele olha o dia inteiro.

Acesso só pela tailnet (Tailscale). Nada do painel é alcançável pela internet.

## O que o produto torna possível

Operar três coisas que hoje só existem por SSH, da mesma tela:

1. **Servidor de Minecraft** — ligar/desligar, console RCON, jogadores, mundos
   (com upload e download), backups com envio para Google Drive, agendamento,
   editor de arquivos, ícone do servidor e configuração validada.
2. **Stack igenda** — ligar/desligar os projetos Docker `igenda` (3 containers)
   e `supabase` (11 containers), respeitando a dependência entre eles, com
   detalhe por container quando preciso.
3. **Energia da máquina** — o host se desliga às 23:00 e acorda às 07:00 por
   `rtcwake`. O painel liga/desliga esse agendamento, edita os horários e
   permite pular uma única noite.

O mecanismo que diferencia: o painel **controla** containers existentes em vez
de ser dono deles. É o que preserva os limites de cgroup, `cpu_shares` e
`oom_score_adj` que impedem o Minecraft de derrubar o Postgres do igenda na
mesma máquina. Painéis prontos (Crafty, Pterodactyl) rodam o servidor por conta
própria e descartariam essas proteções.

## Estados importantes

Cada alvo controlável tem: no ar, subindo, parado, com defeito, em transição.
Operações longas são comuns e precisam de feedback honesto — backup de 2 GB leva
~75 s, restauração ~105 s, upload de mundo de 1,8 GB ~50 s, boot do Minecraft
35–65 s conforme o tamanho do mundo.

Erros são informação de operação, não exceções: servidor parado, RCON indispo-
nível, disco cheio, destino do rclone inacessível.

## Fatos que trabalhos futuros precisam preservar

- **Hierarquia de risco.** O igenda é produção/homologação de um produto
  comercial. O Minecraft é lazer. Nenhuma ação de Minecraft pode ameaçar o
  igenda, e a interface não pode tornar fácil derrubar o igenda sem querer.
- **Dependência.** `igenda` depende de `supabase`. Subir: supabase primeiro.
  Descer: igenda primeiro.
- **Ações destrutivas** (restaurar backup, apagar mundo, desligar containers de
  produção, desligar a máquina) exigem confirmação explícita.
- **Operações demoradas** precisam de estado visível; o usuário não pode ficar
  sem saber se travou.
- **Segurança.** O painel tem o socket do Docker montado e acesso ao host por
  `nsenter`: é root na máquina. Só na tailnet, só com senha, nunca `0.0.0.0`.
- **Validação no servidor.** Todo valor de configuração é validado contra um
  domínio antes de ser escrito no `.env`.
- **Fuso.** Host em UTC; painel e servidor em America/Sao_Paulo. Horários na
  interface são sempre de São Paulo.
- **Português do Brasil** em toda a interface.

## Stack

Flask + Jinja + HTMX, CSS próprio sem build step, servido de um container Docker
ao lado dos outros. Escolha já feita e em produção; mantida.

## Compromisso visual

O usuário escolheu explicitamente o padrão da categoria, apontando o **MC Server
Manager** (Natchland) como referência e régua de acabamento: chrome escuro,
barra lateral fixa com a lista de alvos e ações globais, cabeçalho com nome,
estado e os botões Ligar/Reiniciar/Desligar, faixa de recursos, abas primárias
em pílula e sub-abas sublinhadas, conteúdo em cards com as ações alinhadas à
direita de cada linha.

Isso é compromisso, não ponto de partida: convenção executada em fidelidade
total, sem ironia e sem floreio contrabandeado. Trabalhos futuros mantêm esse
vocabulário.

A barra lateral lista tudo como item de mesmo nível — Minecraft, igenda,
Supabase e o Servidor (a máquina em si, onde mora a energia).

## Decisões em aberto

- Sem logo próprio. O painel é interno e nunca teve marca.
