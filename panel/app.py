"""Painel de controle do servidor de Minecraft.

Controla o container itzg que já existe — não substitui. Isso é deliberado: os
limites de cgroup, o `cpu_shares` e o `oom_score_adj` do compose são o que
impede o Minecraft de derrubar o Postgres do igenda na mesma máquina. Um painel
que rodasse o servidor por conta própria jogaria tudo isso fora.

Três superfícies:
  - Docker CLI  -> ciclo de vida (start/stop/restart/logs/stats)
  - compose     -> mudanças de configuração, que exigem recriar o container
  - RCON        -> tudo que o servidor aceita em tempo de execução
"""

import hmac
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import zipfile
from datetime import datetime, timedelta
from functools import wraps
from hashlib import scrypt
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import (Flask, Response, abort, after_this_request, redirect,
                   render_template, request, send_file, session, url_for)

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
MC_DATA = Path(os.environ.get("MC_DATA", "/mcdata"))
PROJECT = Path(os.environ.get("PROJECT_DIR", "/project"))
BACKUPS = Path(os.environ.get("BACKUP_DIR", "/backups"))
PANEL_DATA = Path(os.environ.get("PANEL_DATA", "/paneldata"))
CONTAINER = os.environ.get("MC_CONTAINER", "minecraft")
# Nome do SERVIÇO no compose (≠ nome do container). `compose up -d` sem alvo
# recriaria o próprio painel no meio da requisição e mataria a resposta.
MC_SERVICE = os.environ.get("MC_SERVICE", "mc")
# O painel mora no MESMO projeto compose do Minecraft. Tirar o projeto do boot
# levaria o painel junto: a máquina acordaria às 07:00 sem nada para religar o
# resto pela web. Este container nunca entra nas ações de autostart.
PANEL_CONTAINER = os.environ.get("PANEL_CONTAINER", "painel")
RCON_HOST = os.environ.get("RCON_HOST", "minecraft")
TZ = ZoneInfo(os.environ.get("TZ", "America/Sao_Paulo"))

# Aviso antes de gravar o mundo. Gravar trava o tick: medido neste servidor,
# 5,34 s só no overworld. Sem aviso o jogador leva um congelamento sem
# explicação e acha que caiu.
FLUSH_AVISO_S = 10
FLUSH_AVISO_MSG = ("Gravando o mundo em {s} segundos — o servidor vai travar "
                   "por alguns instantes.")

# Intervalo do autosave do Paper quando o painel assume as gravações.
# 1728000 ticks = 24 h (20 ticks/s).
#
# NÃO é "desligado": o valor que desliga não está documentado pelo Paper, e um
# número em ticks está — a doc só diz "the world saving interval in ticks".
# Adivinhar -1 ou 0 aqui seria apostar o mapa. Com 24 h e a máquina
# reiniciando todo dia, o autosave do Paper na prática nunca dispara; e se o
# painel morrer, sobra uma gravação por dia em vez de nenhuma.
PAPER_AUTOSAVE_TICKS = 1728000
PAPER_WORLD_DEFAULTS = "config/paper-world-defaults.yml"

STATE_FILE = PANEL_DATA / "panel.json"
RCLONE_CONF = PANEL_DATA / "rclone.conf"

# Campos editáveis pelo painel, com o domínio de cada um.
#
# A lista não é só comodidade de interface: o servidor valida contra ela antes
# de escrever no .env. Sem isso qualquer texto do formulário viraria variável
# de ambiente do container.
#
#   select -> valor TEM que estar em options
#   number -> inteiro dentro de [min, max]
#   text   -> casa com `pattern`, limitado em tamanho
#   worlds -> select montado em tempo real com os mundos que existem
FIELDS = {
    "MC_LEVEL": {"label": "Mundo ativo", "type": "worlds",
                 "help": "Trocar aqui recria o container."},
    "MC_MOTD": {"label": "Mensagem na lista de servidores", "type": "text",
                "pattern": r"^[^\r\n]{0,120}$",
                "help": "Aparece embaixo do nome no multiplayer."},
    "MC_DIFFICULTY": {"label": "Dificuldade", "type": "select",
                      "options": ["peaceful", "easy", "normal", "hard"]},
    "MC_GAMEMODE": {"label": "Modo de jogo", "type": "select",
                    "options": ["survival", "creative", "adventure", "spectator"]},
    "MC_PVP": {"label": "PvP entre jogadores", "type": "select",
               "options": ["true", "false"]},
    "MC_ONLINE_MODE": {"label": "Verificar conta na Mojang", "type": "select",
                       "options": ["true", "false"],
                       "help": "false permite conta pirata — e qualquer um usar seu nick."},
    "MC_MAX_PLAYERS": {"label": "Máximo de jogadores", "type": "number",
                       "min": 1, "max": 200},
    "MC_SPAWN_PROTECTION": {"label": "Raio protegido no spawn", "type": "number",
                            "min": 0, "max": 256,
                            "help": "0 desliga. Só operadores constroem dentro do raio."},
    "MC_VIEW_DISTANCE": {"label": "Distância de renderização (chunks)",
                         "type": "number", "min": 3, "max": 32,
                         "help": "Custa RAM e rede. O cliente limita pelo menor dos dois."},
    "MC_SIMULATION_DISTANCE": {"label": "Distância de simulação (chunks)",
                               "type": "number", "min": 3, "max": 32,
                               "help": "Custa CPU. É o que derruba o TPS primeiro."},
    "MC_VERSION": {"label": "Versão do Minecraft", "type": "select",
                   "options": ["LATEST", "26.1", "1.21.4", "1.20.6", "1.20.4", "1.18.2", "1.16.5"],
                   "help": "LATEST flutua: o Mojang lança e seu cliente para de conectar."},
    "MC_JAVA": {"label": "Java da imagem", "type": "select",
                "options": ["java25", "java21", "java17", "java11", "java8"],
                "help": "Precisa acompanhar a versão: 26.1+ exige java25."},
    "MC_HEAP": {"label": "Memória da JVM", "type": "select",
                "options": ["1G", "1500M", "2G", "3G", "4G", "5G", "6G", "7G",
                            "8G", "9G", "10G", "11G", "12G"],
                "help": "Sempre 1 G ABAIXO do limite do container. Com o igenda "
                        "e o Supabase desligados sobra bem mais — veja Tarefas."},
    "MC_MEM_LIMIT": {"label": "Limite de memória do container", "type": "select",
                     "options": ["2G", "3G", "4G", "5G", "6G", "7G", "8G", "9G",
                                 "10G", "11G", "12G", "13G"],
                     "help": "Teto duro do cgroup. Deixe ao menos 2 G para o "
                             "sistema, e mais se for religar o igenda."},
    "MC_CPUS": {"label": "Teto de CPU", "type": "select",
                "options": ["0.5", "1.0", "1.5", "2.0", "2.5", "3.0", "4.0"],
                "help": "A máquina tem 4 núcleos (8 threads)."},
    "MC_OPS": {"label": "Operadores no primeiro boot", "type": "text",
               "pattern": r"^[A-Za-z0-9_,]{0,200}$",
               "help": "Nicks separados por vírgula, sem espaço."},
    "MC_BIND": {"label": "IP onde a porta 25565 escuta", "type": "text",
                "pattern": r"^[0-9.]{7,15}$",
                "help": "IP da tailnet. Nunca 0.0.0.0 — exporia o servidor."},
}
# Campos do formulário "Criar mundo". Os de geração só têm efeito no momento da
# criação: num mundo existente, semente e tipo já estão gravados no level.dat.
# Os de regra valem sempre, para o mundo que estiver ativo.
SIM_NAO = ["true", "false"]
CRIAR_CAMPOS = {
    "MC_SEED": {"label": "Semente", "type": "text", "grupo": "geracao",
                "pattern": r"^[^\r\n]{0,96}$",
                "help": "Vazia = mundo aleatório. Aceita número ou texto."},
    "MC_LEVEL_TYPE": {"label": "Tipo de mundo", "type": "select", "grupo": "geracao",
                      "options": ["minecraft:normal", "minecraft:flat",
                                  "minecraft:large_biomes", "minecraft:amplified",
                                  "minecraft:single_biome_surface"],
                      "help": "amplified exige bastante CPU para gerar."},
    "MC_GENERATE_STRUCTURES": {"label": "Gerar estruturas", "type": "select",
                               "grupo": "geracao", "options": SIM_NAO,
                               "help": "Vilas, fortalezas, templos, portais."},
    "MC_MAX_WORLD_SIZE": {"label": "Raio máximo do mundo (blocos)", "type": "number",
                          "grupo": "geracao", "min": 1, "max": 29999984,
                          "help": "A borda do mundo. 29999984 é o limite do jogo."},

    "MC_DIFFICULTY": {"label": "Dificuldade", "type": "select", "grupo": "regras",
                      "options": ["peaceful", "easy", "normal", "hard"]},
    "MC_GAMEMODE": {"label": "Modo de jogo", "type": "select", "grupo": "regras",
                    "options": ["survival", "creative", "adventure", "spectator"]},
    "MC_HARDCORE": {"label": "Hardcore", "type": "select", "grupo": "regras",
                    "options": SIM_NAO,
                    "help": "Morreu, virou espectador. Força dificuldade hard."},
    "MC_FORCE_GAMEMODE": {"label": "Forçar modo ao entrar", "type": "select",
                          "grupo": "regras", "options": SIM_NAO,
                          "help": "Devolve todo mundo ao modo padrão a cada entrada."},
    "MC_PVP": {"label": "PvP entre jogadores", "type": "select", "grupo": "regras",
               "options": SIM_NAO},
    "MC_ALLOW_NETHER": {"label": "Permitir Nether", "type": "select",
                        "grupo": "regras", "options": SIM_NAO},
    "MC_ALLOW_FLIGHT": {"label": "Permitir voo", "type": "select", "grupo": "regras",
                        "options": SIM_NAO,
                        "help": "Para mods/plugins de voo na sobrevivência."},
    "MC_SPAWN_MONSTERS": {"label": "Gerar monstros", "type": "select",
                          "grupo": "regras", "options": SIM_NAO},
    "MC_SPAWN_ANIMALS": {"label": "Gerar animais", "type": "select",
                         "grupo": "regras", "options": SIM_NAO},
    "MC_SPAWN_NPCS": {"label": "Gerar aldeões", "type": "select", "grupo": "regras",
                      "options": SIM_NAO},
    "MC_COMMAND_BLOCK": {"label": "Blocos de comando", "type": "select",
                         "grupo": "regras", "options": SIM_NAO},
    "MC_SPAWN_PROTECTION": {"label": "Raio protegido no spawn", "type": "number",
                            "grupo": "regras", "min": 0, "max": 256,
                            "help": "0 desliga. Só operadores constroem dentro."},
}

# As regras de jogo também ficam editáveis depois, na aba Configurações.
for _k, _v in CRIAR_CAMPOS.items():
    if _v["grupo"] == "regras" and _k not in FIELDS:
        FIELDS[_k] = {k: v for k, v in _v.items() if k != "grupo"}

EDITABLE_ENV = set(FIELDS) | set(CRIAR_CAMPOS)
ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

# Ícone que aparece na lista de servidores do cliente. O Minecraft exige PNG de
# exatamente 64x64 em /data/server-icon.png e ignora em silêncio qualquer coisa
# fora disso — por isso o painel redimensiona em vez de só validar.
ICON_PATH_NAME = "server-icon.png"
ICON_SIZE = (64, 64)
MAX_ICON_BYTES = 12 * 1024 * 1024

# Arquivos que o editor de texto abre. O resto só dá para baixar/apagar.
TEXT_SUFFIXES = {".properties", ".yml", ".yaml", ".json", ".txt", ".cfg",
                 ".conf", ".toml", ".log", ".md", ".sh"}
MAX_EDIT_BYTES = 1024 * 1024

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # mundo .zip grande
app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
app.config["SESSION_COOKIE_HTTPONLY"] = True

_state_lock = threading.Lock()
_busy_lock = threading.Lock()   # serializa operações pesadas (backup/restore)


# ---------------------------------------------------------------------------
# Estado persistente
# ---------------------------------------------------------------------------
def default_state():
    return {
        "secret_key": secrets.token_hex(32),
        "password": None,          # {salt, hash}
        "schedule": {
            "enabled": False,
            "start_at": "",        # "HH:MM" vazio = desligado
            "stop_at": "",
            "days": [0, 1, 2, 3, 4, 5, 6],   # 0 = segunda
            "restart_at": "",
        },
        # Flush periódico do mundo no disco. Não substitui o autosave do
        # Paper (5 min): só adiciona gravações forçadas no meio dele, para
        # encurtar o que uma queda de energia leva embora.
        "autosave": {
            "enabled": False,
            "every_min": 5,
        },
        "backup": {
            "enabled": False,
            "at": "04:00",
            "keep": 7,
            "remote": "",          # ex.: "gdrive:minecraft" (vazio = só local)
        },
        "audit": [],
        "energia_pular_ate": "",
    }


def load_state():
    with _state_lock:
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
        else:
            data = {}
        base = default_state()
        for k, v in base.items():
            if k not in data:
                data[k] = v
            elif isinstance(v, dict):
                merged = dict(v)
                merged.update(data[k] if isinstance(data[k], dict) else {})
                data[k] = merged
        return data


def save_state(data):
    with _state_lock:
        PANEL_DATA.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), "utf-8")
        tmp.replace(STATE_FILE)


def audit(action, detail=""):
    st = load_state()
    st["audit"].insert(0, {
        "at": now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "detail": detail[:300],
        "user": session.get("user", "sistema") if request else "sistema",
    })
    del st["audit"][200:]
    save_state(st)


def now():
    return datetime.now(TZ)


# ---------------------------------------------------------------------------
# Senha
# ---------------------------------------------------------------------------
def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = scrypt(password.encode(), salt=salt.encode(), n=2**14, r=8, p=1, dklen=32)
    return {"salt": salt, "hash": digest.hex()}


def check_password(password, stored):
    if not stored:
        return False
    calc = hash_password(password, stored["salt"])
    return hmac.compare_digest(calc["hash"], stored["hash"])


def ensure_password():
    """Primeira subida: gera senha aleatória e joga no log do container.

    Sem senha padrão — um painel com docker.sock e credencial conhecida é um
    convite. A senha só aparece no `docker compose logs panel`.
    """
    st = load_state()
    if st.get("password"):
        return None
    pw = secrets.token_urlsafe(12)
    st["password"] = hash_password(pw)
    save_state(st)
    return pw


# ---------------------------------------------------------------------------
# Auth + CSRF
# ---------------------------------------------------------------------------
def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("user"):
            if request.headers.get("HX-Request"):
                return Response("sessão expirada", 401, {"HX-Redirect": url_for("login")})
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapper


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


@app.before_request
def verify_csrf():
    if request.method not in ("POST", "PUT", "DELETE"):
        return
    if request.endpoint == "login":
        return
    sent = request.headers.get("X-CSRF") or request.form.get("csrf", "")
    if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
        abort(400, "token CSRF inválido")


# ---------------------------------------------------------------------------
# Docker / compose
# ---------------------------------------------------------------------------
def run_cmd(args, timeout=300, check=False):
    """Executa sem shell. Nenhuma entrada do usuário vira string de comando."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout após {timeout}s"
    except FileNotFoundError as e:
        return 127, "", str(e)
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}: {p.stderr.strip()}")
    return p.returncode, p.stdout, p.stderr


def docker(*args, **kw):
    return run_cmd(["docker", *args], **kw)


def compose(*args, **kw):
    return run_cmd([
        "docker", "compose",
        "-f", str(PROJECT / "docker-compose.yml"),
        "--env-file", str(PROJECT / ".env"),
        *args,
    ], **kw)


def container_state():
    code, out, _ = docker("inspect", CONTAINER, "--format",
                          "{{.State.Status}}|{{.State.Health.Status}}|{{.State.StartedAt}}")
    if code != 0:
        return {"status": "ausente", "health": "-", "uptime": "-"}
    status, health, started = (out.strip().split("|") + ["", "", ""])[:3]
    # Container parado guarda o último health. Mostrar "unhealthy" num servidor
    # que só está desligado faz parecer defeito onde não há.
    if status != "running":
        health = "-"
    uptime = "-"
    if status == "running" and started:
        try:
            t0 = datetime.fromisoformat(started.replace("Z", "+00:00"))
            secs = int((datetime.now(t0.tzinfo) - t0).total_seconds())
            uptime = f"{secs // 3600}h {secs % 3600 // 60}m"
        except ValueError:
            pass
    return {"status": status, "health": health or "-", "uptime": uptime}


def container_stats():
    code, out, _ = docker("stats", "--no-stream", "--format",
                          "{{.MemUsage}}|{{.MemPerc}}|{{.CPUPerc}}", CONTAINER, timeout=20)
    if code != 0 or not out.strip():
        return {"mem": "-", "mem_pct": "-", "cpu": "-"}
    mem, mem_pct, cpu = (out.strip().split("|") + ["-", "-", "-"])[:3]
    return {"mem": mem, "mem_pct": mem_pct, "cpu": cpu}


# ---------------------------------------------------------------------------
# Alvos controláveis
#
# A barra lateral lista tudo no mesmo nível: as três pilhas Docker e a própria
# máquina. `risco` não é decoração — é o que faz o botão de desligar produção
# pedir confirmação enquanto o do Minecraft não pede.
# ---------------------------------------------------------------------------
ALVOS = {
    "minecraft": {
        "label": "Minecraft", "tipo": "minecraft", "projeto": "minecraft",
        "sub": "Paper · servidor de jogo", "risco": "lazer",
        "abas": [("visao", "Visão geral"), ("console", "Console"),
                 ("jogadores", "Jogadores"), ("conteudo", "Conteúdo"),
                 ("automacao", "Automação"), ("config", "Configurações")],
    },
    "igenda": {
        "label": "igenda", "tipo": "pilha", "projeto": "igenda",
        "sub": "API, painel e túnel", "risco": "producao",
        "depende_de": "supabase",
        "abas": [("visao", "Visão geral"), ("containers", "Containers"),
                 ("console", "Log")],
    },
    "supabase": {
        "label": "Supabase", "tipo": "pilha", "projeto": "supabase",
        "sub": "Banco, auth e storage", "risco": "producao",
        "exigido_por": "igenda",
        "abas": [("visao", "Visão geral"), ("containers", "Containers"),
                 ("console", "Log")],
    },
    "servidor": {
        "label": "Servidor", "tipo": "host", "projeto": None,
        "sub": "A máquina em si", "risco": "host",
        "abas": [("visao", "Visão geral"), ("tarefas", "Tarefas"),
                 ("energia", "Energia"), ("historico", "Histórico")],
    },
}

# Imagem mínima usada só para alcançar o host. `nsenter -t 1` entra nos
# namespaces do PID 1, que é o systemd da máquina — é assim que o painel
# consulta e mexe no timer de energia sem precisar de sudo nem agente no host.
HOST_HELPER_IMAGE = os.environ.get("HOST_HELPER_IMAGE", "alpine:3.20")
HOST_TIMER = "desliga-ate-manha.timer"
HOST_SERVICE = "desliga-ate-manha.service"
HOST_UNIT = "/etc/systemd/system/desliga-ate-manha.timer"
HOST_SCRIPT = "/usr/local/bin/desliga-ate-manha"
# Índice = isoweekday() - 1. O script do host numera 1..7 como `date +%u`.
DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
DIAS_SYSTEMD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Minutos de aviso no chat antes de dormir. O timer dispara esse tanto antes
# do horário de dormir; o script do host avisa, espera e só então desliga.
# Tem que bater com o default de AVISO_MIN no script.
AVISO_MIN = 15

# Agenda semanal: {1..7: {"acorda": "HH:MM", "dorme": "HH:MM",
#                         "liga_acorda": bool, "liga_dorme": bool}}.
# Mora nas linhas DIA_n= do script do host; o OnCalendar do timer é gerado a
# partir dela. Uma fonte só: o painel nunca lê o timer para saber a agenda.
# Toggle desligado guarda o horário com "~" na frente, para não perder.
DIA_PADRAO = {"acorda": "08:00", "dorme": "00:00",
              "liga_acorda": False, "liga_dorme": False}


def ler_agenda(script):
    """Agenda lida das linhas DIA_n= do script. Dia sem linha fica de fora —
    `len(...) == 7` é o teste de "o script do host é o novo". `DIA_n=` vazio
    (formato anterior) = os dois toggles desligados."""
    agenda = {}
    for n in range(1, 8):
        m = re.search(rf"^DIA_{n}=(?:(~?)(\d{{2}}:\d{{2}})-(~?)(\d{{2}}:\d{{2}}))?[ \t]*$",
                      script, re.M)
        if not m:
            continue
        if m.group(2) is None:
            agenda[n] = dict(DIA_PADRAO)
        else:
            agenda[n] = {"acorda": m.group(2), "dorme": m.group(4),
                         "liga_acorda": not m.group(1),
                         "liga_dorme": not m.group(3)}
    return agenda


def proxima_acordada(apos, agenda):
    """Mesma conta do script do host: hoje se o dia acorda sozinho e a hora
    não passou, senão o próximo dia que acorda. Só serve para MOSTRAR — quem
    arma o despertador é o script."""
    for n in range(8):
        d = apos + timedelta(days=n)
        dia = agenda.get(d.isoweekday())
        if not dia or not dia["liga_acorda"]:
            continue
        hh, mm = (int(x) for x in dia["acorda"].split(":"))
        alvo = d.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if alvo > apos:
            return alvo
    return None


def fmt_acordada(quando):
    if not quando:
        return "—"
    return f"{DIAS_SEMANA[quando.weekday()]} {quando:%d/%m} às {quando:%H:%M}"


def oncalendar_da_agenda(agenda):
    """Linhas OnCalendar= do timer: AVISO_MIN antes de cada horário de dormir
    ligado. Dorme <= acorda = madrugada do dia seguinte: sáb 08:00-00:00
    desliga domingo 00:00, e o timer dispara sábado 23:45."""
    linhas = []
    for n, dia in sorted(agenda.items()):
        if not dia["liga_dorme"]:
            continue
        hh, mm = (int(x) for x in dia["dorme"].split(":"))
        minutos = hh * 60 + mm - AVISO_MIN
        semana = n - 1 if dia["dorme"] > dia["acorda"] else n % 7
        semana = (semana + minutos // 1440) % 7     # aviso antes da meia-noite
        minutos %= 1440
        linhas.append(f"OnCalendar={DIAS_SYSTEMD[semana]} *-*-* "
                      f"{minutos // 60:02d}:{minutos % 60:02d}:00 America/Sao_Paulo")
    return linhas


def sed_agenda(agenda):
    """Argumentos `-e` do sed que trocam as linhas DIA_n= do script."""
    exprs = []
    for n, dia in sorted(agenda.items()):
        valor = (f"{'' if dia['liga_acorda'] else '~'}{dia['acorda']}-"
                 f"{'' if dia['liga_dorme'] else '~'}{dia['dorme']}")
        exprs += ["-e", f"s|^DIA_{n}=.*|DIA_{n}={valor}|"]
    return exprs


def sed_timer(agenda):
    """Argumentos `-e` do sed que trocam TODAS as OnCalendar= do timer.
    Os `a` no mesmo endereço saem na ordem em que aparecem (GNU sed)."""
    exprs = ["-e", "/^OnCalendar=/d"]
    for linha in oncalendar_da_agenda(agenda):
        exprs += ["-e", f"/^\\[Timer\\]/a {linha}"]
    return exprs


def host_run(*args, timeout=180):
    return run_cmd(["docker", "run", "--rm", "--privileged", "--pid=host",
                    HOST_HELPER_IMAGE, "nsenter", "-t", "1", "-m", "-u", "-i",
                    "-n", "--", *args], timeout=timeout)


def project_containers(projeto):
    """Containers de um projeto compose, lidos pelo label — sem precisar do
    arquivo. É o que permite controlar igenda e supabase sem montar os repos
    deles dentro do painel."""
    code, out, _ = docker(
        "ps", "-a",
        "--filter", f"label=com.docker.compose.project={projeto}",
        "--format", '{{.Names}}\t{{.State}}\t{{.Status}}\t{{.Label "com.docker.compose.service"}}',
        timeout=30)
    itens = []
    if code != 0:
        return itens
    for linha in out.strip().splitlines():
        partes = (linha.split("\t") + ["", "", "", ""])[:4]
        nome, estado, status, servico = partes
        itens.append({"nome": nome, "estado": estado, "status": status,
                      "servico": servico or nome})
    itens.sort(key=lambda c: c["servico"])
    return itens


# "Done (9.195s)! For help, type "help"" é a linha em que o Paper termina de
# carregar o mundo e passa a aceitar jogador. Antes dela o container está
# rodando e o servidor não atende — dizer "no ar" ali é mentira.
PRONTO_RE = re.compile(r'Done \([\d.]+s\)! For help')


def minecraft_pronto():
    """True só depois do Done desta execução.

    O `--since` com o StartedAt é essencial: o log do container sobrevive a
    restart, e sem o filtro um Done da execução anterior daria pronto na hora.
    """
    code, out, _ = docker("inspect", CONTAINER, "--format", "{{.State.StartedAt}}",
                          timeout=20)
    if code != 0:
        return False
    desde = out.strip()
    code, out, err = docker("logs", "--since", desde, "--tail", "400", CONTAINER,
                            timeout=30)
    if code != 0:
        return False
    return bool(PRONTO_RE.search(out + err))


def estado_alvo(chave):
    """Resumo de um alvo: no ar / subindo / parcial / parado."""
    spec = ALVOS[chave]
    if spec["tipo"] == "host":
        return {"estado": "no-ar", "rotulo": "ligado", "no_ar": 1, "total": 1}
    if spec["tipo"] == "minecraft":
        cs = container_state()
        if cs["status"] != "running":
            rot = "parado" if cs["status"] != "ausente" else "sem container"
            return {"estado": "parado", "rotulo": rot, "no_ar": 0, "total": 1,
                    "containers": []}
        if minecraft_pronto():
            return {"estado": "no-ar", "rotulo": "no ar", "no_ar": 1, "total": 1,
                    "containers": []}
        return {"estado": "parcial", "rotulo": "subindo", "no_ar": 0, "total": 1,
                "containers": []}
    conts = project_containers(spec["projeto"])
    no_ar = sum(1 for c in conts if c["estado"] == "running")
    total = len(conts)
    if total == 0:
        estado, rotulo = "ausente", "sem containers"
    elif no_ar == total:
        estado, rotulo = "no-ar", "no ar"
    elif no_ar == 0:
        estado, rotulo = "parado", "parado"
    else:
        estado, rotulo = "parcial", f"{no_ar} de {total}"
    return {"estado": estado, "rotulo": rotulo, "no_ar": no_ar, "total": total,
            "containers": conts}


def _agir_containers(projeto, acao, timeout=300):
    conts = project_containers(projeto)
    if not conts:
        return False, f"nenhum container no projeto {projeto}"
    nomes = [c["nome"] for c in conts]
    args = ["stop", "-t", "30"] if acao == "stop" else [acao]
    code, out, err = docker(*args, *nomes, timeout=timeout)
    return code == 0, (err or out).strip()[-400:]


def pilha_acao(chave, acao):
    """Liga/desliga respeitando a dependência.

    Subir o igenda sem o supabase de pé dá um container saudável que não
    atende nada. Descer o supabase antes do igenda deixa a API gritando no log
    por minutos. A ordem está aqui para o usuário não precisar lembrar dela.
    """
    spec = ALVOS[chave]
    passos = []
    if acao == "start":
        if spec.get("depende_de"):
            passos.append(spec["depende_de"])
        passos.append(chave)
    elif acao == "stop":
        if spec.get("exigido_por"):
            passos.append(spec["exigido_por"])
        passos.append(chave)
    else:
        passos.append(chave)

    feitos, falhas = [], []
    for alvo in passos:
        ok, msg = _agir_containers(ALVOS[alvo]["projeto"], acao)
        (feitos if ok else falhas).append(f"{ALVOS[alvo]['label']}" + ("" if ok else f" ({msg})"))
    if falhas:
        return False, "falhou em " + ", ".join(falhas)
    return True, " → ".join(feitos)


# ---------------------------------------------------------------------------
# Subir sozinho no boot
#
# É a política de restart do Docker, não um arquivo nosso. `unless-stopped`
# sobe no boot; `no` não sobe. Ler do próprio Docker evita o painel afirmar uma
# coisa enquanto a máquina faz outra.
# ---------------------------------------------------------------------------
def _autostart_alvos(projeto):
    """Containers do projeto, menos o do próprio painel."""
    return [c for c in project_containers(projeto) if c["nome"] != PANEL_CONTAINER]


def autostart_estado(projeto):
    conts = _autostart_alvos(projeto)
    if not conts:
        return {"ligado": False, "misto": False, "total": 0}
    politicas = []
    for c in conts:
        _, out, _ = docker("inspect", c["nome"], "--format",
                           "{{.HostConfig.RestartPolicy.Name}}", timeout=20)
        politicas.append(out.strip() or "no")
    # Só `always`. `unless-stopped` NÃO sobe no boot se o container foi parado
    # na mão antes de desligar a máquina — e era exatamente esse o estado em
    # que o painel dizia "sobe sozinho no boot" e o Minecraft não subia.
    ligados = sum(1 for p in politicas if p == "always")
    return {"ligado": ligados == len(politicas), "misto": 0 < ligados < len(politicas),
            "total": len(politicas), "ligados": ligados}


def autostart_definir(projeto, ligado):
    conts = _autostart_alvos(projeto)
    if not conts:
        return False, "nenhum container neste projeto"
    politica = "always" if ligado else "no"
    nomes = [c["nome"] for c in conts]
    code, out, err = docker("update", f"--restart={politica}", *nomes, timeout=180)
    if code != 0:
        return False, (err or out).strip()[-300:]
    # `docker update` morre no primeiro recreate, e a aba Configuração roda
    # `compose up -d mc` a cada salvamento. Gravar no .env é o que faz a
    # escolha durar: o compose lê `restart: ${MC_RESTART:-unless-stopped}`.
    # Só para o projeto deste repositório — igenda e supabase têm o compose
    # deles, fora do alcance do painel.
    aviso = ""
    if projeto == "minecraft":
        try:
            write_env({"MC_RESTART": politica})
        except OSError as e:
            aviso = (f" Não consegui gravar no .env ({e}): salvar algo na aba "
                     "Configuração vai desfazer isto.")
    return True, (("Sobe sozinho no boot, mesmo que você tenha desligado antes."
                   if ligado else
                   "Não sobe mais sozinho — você liga pelo painel quando quiser.")
                  + aviso)


# ---------------------------------------------------------------------------
# Gerenciador de tarefas
# ---------------------------------------------------------------------------
def _bytes_de(texto):
    """'6.628GiB' -> bytes. docker stats devolve string formatada."""
    m = re.match(r"([\d.]+)\s*([KMGT]?i?B)", texto.strip(), re.I)
    if not m:
        return 0
    n = float(m.group(1))
    mult = {"b": 1, "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4,
            "kb": 1000, "mb": 1000**2, "gb": 1000**3, "tb": 1000**4}
    return int(n * mult.get(m.group(2).lower(), 1))


def tarefas():
    """Uso de CPU e memória por container, agrupado por pilha, mais o host."""
    code, out, _ = docker("stats", "--no-stream", "--format",
                          "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.PIDs}}",
                          timeout=40)
    # Nome do container -> projeto, para agrupar.
    projeto_de = {}
    for chave, spec in ALVOS.items():
        if spec.get("projeto"):
            for c in project_containers(spec["projeto"]):
                projeto_de[c["nome"]] = chave

    itens = []
    if code == 0:
        for linha in out.strip().splitlines():
            p = linha.split("|")
            if len(p) < 5:
                continue
            nome, cpu, mem, mempct, pids = p[:5]
            usado = mem.split("/")[0].strip()
            itens.append({
                "nome": nome,
                "alvo": projeto_de.get(nome),
                "cpu": cpu.strip(),
                "cpu_num": float(cpu.strip().rstrip("%") or 0),
                "mem": usado,
                "mem_bytes": _bytes_de(usado),
                "mem_pct": mempct.strip(),
                "pids": pids.strip(),
            })

    # Host: total de memória, núcleos e carga, lidos direto do /proc.
    _, h, _ = host_run("sh", "-c",
                       "nproc; awk '/MemTotal|MemAvailable/{print $2}' /proc/meminfo; "
                       "cut -d' ' -f1-3 /proc/loadavg", timeout=120)
    linhas = (h.strip().splitlines() + ["0"] * 4)[:4]
    try:
        nucleos = int(linhas[0])
        mem_total = int(linhas[1]) * 1024
        mem_livre = int(linhas[2]) * 1024
    except (ValueError, IndexError):
        nucleos, mem_total, mem_livre = 1, 0, 0

    # docker stats mede CPU sobre UM núcleo: 800% é a máquina inteira aqui.
    # Normalizar evita o painel dizer "320%" para quem tem 8 threads.
    for it in itens:
        it["cpu_maq"] = round(it["cpu_num"] / max(nucleos, 1), 1)

    grupos = []
    for chave in ("minecraft", "igenda", "supabase"):
        do_grupo = [i for i in itens if i["alvo"] == chave]
        grupos.append({
            "chave": chave, "label": ALVOS[chave]["label"], "itens": do_grupo,
            "cpu": round(sum(i["cpu_maq"] for i in do_grupo), 1),
            "mem_bytes": sum(i["mem_bytes"] for i in do_grupo),
            "mem": human_size(sum(i["mem_bytes"] for i in do_grupo)),
        })
    outros = [i for i in itens if i["alvo"] is None]
    if outros:
        grupos.append({
            "chave": "outros", "label": "Outros containers", "itens": outros,
            "cpu": round(sum(i["cpu_maq"] for i in outros), 1),
            "mem_bytes": sum(i["mem_bytes"] for i in outros),
            "mem": human_size(sum(i["mem_bytes"] for i in outros)),
        })

    mem_usada = mem_total - mem_livre
    return {
        "grupos": grupos, "nucleos": nucleos, "carga": linhas[3],
        "mem_total": human_size(mem_total), "mem_usada": human_size(mem_usada),
        "mem_livre": human_size(mem_livre),
        "mem_pct": round(mem_usada / mem_total * 100, 1) if mem_total else 0,
        "cpu_total": round(sum(i["cpu_maq"] for i in itens), 1),
        "containers_mem_pct": round(
            sum(i["mem_bytes"] for i in itens) / mem_total * 100, 1) if mem_total else 0,
    }


# ---------------------------------------------------------------------------
# Energia do host
# ---------------------------------------------------------------------------
def energia_estado():
    """Lê o timer do systemd no host. Tudo aqui é leitura."""
    info = {"disponivel": False, "ligado": False, "ativo": False,
            "proximo": "—", "erro": "", "agenda": {},
            "acorda_depois": "—", "acorda_agora": "—"}
    # --timestamp=unix é obrigatório: sem ele NextElapseUSecRealtime volta como
    # "Fri 2026-11-06 02:00:00 UTC", data formatada e dependente de locale, em
    # vez de número. Com ele vem "@1762394400", que dá para converter.
    code, out, err = host_run("systemctl", "show", HOST_TIMER, "--timestamp=unix",
                              "-p", "UnitFileState", "-p", "ActiveState",
                              "-p", "NextElapseUSecRealtime", timeout=120)
    if code != 0:
        info["erro"] = (err or out).strip()[-300:] or "não consegui falar com o host"
        return info
    campos = {}
    for linha in out.strip().splitlines():
        if "=" in linha:
            k, v = linha.split("=", 1)
            campos[k.strip()] = v.strip()
    info["disponivel"] = True
    info["ligado"] = campos.get("UnitFileState") == "enabled"
    info["ativo"] = campos.get("ActiveState") == "active"

    bruto = campos.get("NextElapseUSecRealtime", "").lstrip("@")
    dorme_em = None
    if bruto.isdigit() and int(bruto) > 0:
        # O timer dispara AVISO_MIN antes: o desligamento é depois do aviso.
        dorme_em = datetime.fromtimestamp(int(bruto), TZ) + timedelta(minutes=AVISO_MIN)
        info["proximo"] = fmt_acordada(dorme_em)

    _, script, _ = host_run("cat", HOST_SCRIPT, timeout=60)
    agenda = ler_agenda(script)
    info["agenda"] = agenda
    agora = datetime.now(TZ)
    info["acorda_agora"] = fmt_acordada(proxima_acordada(agora, agenda))
    info["acorda_depois"] = fmt_acordada(
        proxima_acordada(dorme_em or agora, agenda))
    return info


def energia_definir_agenda(agenda):
    """Grava a agenda no script do host e regenera o OnCalendar do timer.
    Só HH:MM validado chega aqui, e ao menos um dia ligado."""
    if not oncalendar_da_agenda(agenda):
        return False, ("Nenhum dia dorme sozinho, e o systemd recusa timer sem "
                       "horário. Ligue o dormir de algum dia, ou use \"Desligar "
                       "agendamento\" — o acordar continua valendo quando você "
                       "desliga pelo painel.")
    # Um sed por arquivo: cada host_run sobe um container.
    code, out, err = host_run("sed", "-i", *sed_agenda(agenda), HOST_SCRIPT,
                              timeout=60)
    if code != 0:
        return False, (err or out).strip()[-300:]
    # `sed` não reclama quando não casa nada. Sem conferir, um script antigo
    # no host (sem as linhas DIA_n=) deixaria o painel dizendo "agenda salva"
    # e a máquina acordando no horário velho.
    _, texto, _ = host_run("cat", HOST_SCRIPT, timeout=60)
    if ler_agenda(texto) != agenda:
        return False, ("o script do host não tem as linhas DIA_1..7= que o painel "
                       "edita — nada mudou. Reinstale host/desliga-ate-manha.")
    code, out, err = host_run("sed", "-i", *sed_timer(agenda), HOST_UNIT,
                              timeout=60)
    if code != 0:
        return False, "script salvo, timer não: " + (err or out).strip()[-200:]
    _, unit, _ = host_run("cat", HOST_UNIT, timeout=60)
    if re.findall(r"^OnCalendar=.*$", unit, re.M) != oncalendar_da_agenda(agenda):
        return False, ("script salvo, mas o timer não ficou com os horários de "
                       f"dormir. Confira {HOST_UNIT}.")
    host_run("systemctl", "daemon-reload", timeout=120)
    if energia_estado().get("ligado"):
        host_run("systemctl", "restart", HOST_TIMER, timeout=120)
    return True, "Agenda salva."


def energia_ligar(ligado):
    acao = ["enable", "--now"] if ligado else ["disable", "--now"]
    code, out, err = host_run("systemctl", *acao, HOST_TIMER, timeout=120)
    if code != 0:
        return False, (err or out).strip()[-300:]
    st = load_state()
    st["energia_pular_ate"] = ""
    save_state(st)
    return True, "Agendamento ligado." if ligado else "Agendamento desligado."


def energia_pular_noite():
    """Para o timer só por hoje — e a contagem do aviso, se já começou.

    `stop` (e não `disable`) mantém o agendamento habilitado: o timer volta
    sozinho no próximo boot. Como pular a noite significa justamente que não
    vai haver boot, o laço do agendador religa o timer quando o dia virar.
    Parar o service mata o script no meio do aviso de 15 min, antes do
    desligamento.
    """
    _, ativo, _ = host_run("systemctl", "is-active", HOST_SERVICE, timeout=60)
    code, out, err = host_run("systemctl", "stop", HOST_TIMER, HOST_SERVICE,
                              timeout=120)
    if code != 0:
        return False, (err or out).strip()[-300:]
    if ativo.strip() in ("active", "activating"):
        try_rcon("say Desligamento cancelado pelo painel. A máquina fica ligada.")
    st = load_state()
    st["energia_pular_ate"] = now().strftime("%Y-%m-%d")
    save_state(st)
    return True, "A máquina não desliga esta noite. Volta ao normal amanhã."


def energia_retomar_se_passou():
    """Chamado pelo laço do agendador: desfaz o 'pular esta noite'."""
    st = load_state()
    dia = st.get("energia_pular_ate") or ""
    if not dia or now().strftime("%Y-%m-%d") <= dia:
        return
    if energia_estado().get("ligado"):
        host_run("systemctl", "start", HOST_TIMER, timeout=120)
        log_system("energia: agendamento retomado depois do pular-esta-noite")
    st["energia_pular_ate"] = ""
    save_state(st)


# ---------------------------------------------------------------------------
# RCON
# ---------------------------------------------------------------------------
def read_properties():
    path = MC_DATA / "server.properties"
    props = {}
    if path.exists():
        for line in path.read_text("utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
    return props


# O Minecraft colore a saída com § seguido de um caractere. No terminal vira
# cor; numa página vira lixo no meio do texto ("§6TPS from last 1m: §a20.0§r").
COLOR_CODE = re.compile("§[0-9a-fk-orA-FK-OR]")

# Sequências de escape de terminal (o "[K" que aparecia colado no horário) e a
# linha de prompt do console do Paper, que é só ">" seguido de pontos.
ANSI_RE = re.compile(chr(27) + r"(?:\[[0-?]*[ -/]*[@-~]|[=>NOc78DEHM])")
# O prompt do console do Paper. Vem de duas formas: linha só com ">", e
# ">...." COLADO numa mensagem real. Exigir ao menos um ponto preserva o eco
# de comando ("> say oi"), que é log de verdade e não ruído.
PROMPT_RE = re.compile(r"^\s*>\s*$")
PROMPT_PREFIXO = re.compile(r"^\s*>\.+\s*")


# Uma conexão RCON viva, reaproveitada. Conectar e desconectar a cada consulta
# fazia o Paper escrever três linhas no console por vez (o "Thread RCON Client
# started", o prompt e o "shutting down") — com polling, isso enterrava o log
# do jogo. Filtrar era remendo; não abrir a conexão é o conserto.
_rcon_viva = {"cli": None}
_rcon_viva_lock = threading.Lock()


def rcon_fechar():
    with _rcon_viva_lock:
        cli = _rcon_viva.get("cli")
        _rcon_viva["cli"] = None
    if cli:
        try:
            cli.close()
        except Exception:
            pass


def rcon(cmd):
    """Credencial lida do server.properties montado — nada duplicado no .env."""
    import mcrcon
    # Servidor desligado é o caso comum, não falha de sistema. Sem isto o
    # usuário recebe "Temporary failure in name resolution", que não diz nada.
    if container_state()["status"] != "running":
        rcon_fechar()
        raise RuntimeError("servidor parado — ligue antes de enviar comandos")
    props = read_properties()
    if props.get("enable-rcon", "false").lower() != "true":
        raise RuntimeError("RCON desabilitado no server.properties")
    password = props.get("rcon.password", "")
    if not password:
        raise RuntimeError("rcon.password vazio")

    porta = props.get("rcon.port", "25575")
    with _rcon_viva_lock:
        # Duas tentativas: a primeira pode cair numa conexão que morreu com o
        # servidor reiniciando. A segunda reconecta e é a que vale.
        for tentativa in (1, 2):
            cli = _rcon_viva.get("cli")
            if cli is None:
                cli = mcrcon.Rcon(RCON_HOST, porta, password)
                cli.connect()
                _rcon_viva["cli"] = cli
            try:
                return COLOR_CODE.sub("", cli.command(cmd))
            except Exception:
                try:
                    cli.close()
                except Exception:
                    pass
                _rcon_viva["cli"] = None
                if tentativa == 2:
                    raise


_rcon_cache = {"em": 0.0, "valor": None}
_rcon_lock = threading.Lock()


def jogadores_online(ttl=3.0):
    """Cacheia por alguns segundos.

    Cabeçalho e aba Jogadores pedem a mesma coisa a cada 8s, e cada conexão RCON
    faz o Paper escrever duas linhas no console ("Thread RCON Client started /
    shutting down"). Uma consulta compartilhada corta esse ruído pela metade.
    """
    agora = time.time()
    with _rcon_lock:
        if _rcon_cache["valor"] is not None and agora - _rcon_cache["em"] < ttl:
            return _rcon_cache["valor"]
    valor = _jogadores_online_agora()
    with _rcon_lock:
        _rcon_cache.update(em=agora, valor=valor)
    return valor


def _jogadores_online_agora():
    """Transforma a resposta do `list` em dados.

    O RCON devolve uma frase: "There are 1 of a max of 4 players online:
    PCantarutti". Para empilhar nomes com o rosto da skin, isso precisa virar
    número e lista, não texto corrido.
    """
    if container_state()["status"] != "running":
        return {"ok": False, "motivo": "servidor parado", "online": 0, "max": 0, "nomes": []}
    try:
        bruto = rcon("list")
    except Exception as e:
        return {"ok": False, "motivo": str(e), "online": 0, "max": 0, "nomes": []}
    m = re.search(r"(\d+)\s+of\s+a\s+max\s+of\s+(\d+)[^:]*:(.*)", bruto, re.S)
    if not m:
        return {"ok": True, "motivo": bruto, "online": 0, "max": 0, "nomes": []}
    nomes = [n.strip() for n in m.group(3).split(",") if n.strip()]
    return {"ok": True, "motivo": "", "online": int(m.group(1)),
            "max": int(m.group(2)), "nomes": nomes}


def try_rcon(cmd):
    try:
        return rcon(cmd)
    except Exception as e:   # servidor parado é o caso normal, não erro
        return f"[rcon indisponível] {e}"


# ---------------------------------------------------------------------------
# .env do projeto
# ---------------------------------------------------------------------------
def read_env():
    path = PROJECT / ".env"
    values = {}
    if path.exists():
        for line in path.read_text("utf-8", errors="replace").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                values[k.strip()] = v.strip()
    return values


def write_env(updates):
    """Reescreve preservando comentários e ordem — o .env é documentação viva."""
    path = PROJECT / ".env"
    lines = path.read_text("utf-8", errors="replace").splitlines() if path.exists() else []
    pending = dict(updates)
    out = []
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            key = s.split("=", 1)[0].strip()
            if key in pending:
                out.append(f"{key}={pending.pop(key)}")
                continue
        out.append(line)
    for k, v in pending.items():
        out.append(f"{k}={v}")
    # Preserva dono e permissão. O painel roda como root e `replace` troca o
    # dono do arquivo: sem isto, depois da primeira gravação o usuário do
    # servidor não consegue mais editar o .env por SSH.
    try:
        st = path.stat()
        dono, grupo, modo = st.st_uid, st.st_gid, st.st_mode & 0o777
    except OSError:
        dono = grupo = modo = None
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(out) + "\n", "utf-8")
    if dono is not None and os.name == "posix":
        try:
            os.chown(tmp, dono, grupo)
            os.chmod(tmp, modo)
        except OSError:
            pass
    tmp.replace(path)


def apply_config():
    """Recria o container do Minecraft com o .env novo.

    O alvo `MC_SERVICE` é obrigatório: sem ele o compose recriaria também o
    container do painel, que é quem está rodando este código.
    """
    code, out, err = compose("up", "-d", MC_SERVICE, timeout=600)
    return code == 0, (err or out).strip()[-1500:]


# ---------------------------------------------------------------------------
# Caminhos seguros
# ---------------------------------------------------------------------------
def safe_path(root: Path, relative: str) -> Path:
    """Impede ../ escapar da raiz. Qualquer caminho vindo do browser passa aqui."""
    root = root.resolve()
    target = (root / relative.lstrip("/")).resolve()
    if target != root and root not in target.parents:
        abort(400, "caminho fora da área permitida")
    return target


SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")


def safe_name(name):
    name = (name or "").strip()
    if not SAFE_NAME.match(name):
        abort(400, "nome inválido: use letras, números, espaço, ponto, hífen ou _")
    return name


# ---------------------------------------------------------------------------
# Mundos
# ---------------------------------------------------------------------------
def list_worlds():
    active = read_properties().get("level-name", "world")
    worlds = []
    if MC_DATA.exists():
        for d in sorted(MC_DATA.iterdir()):
            # Ignora .upload-* e .tmp: diretórios de trabalho não são mundos.
            if d.name.startswith("."):
                continue
            if d.is_dir() and (d / "level.dat").exists():
                worlds.append({
                    "name": d.name,
                    "active": d.name == active,
                    "size": human_size(dir_size(d)),
                })
    return worlds


def chown_like_data(path: Path):
    """Dá ao arquivo/pasta o mesmo dono do /data.

    O painel roda como root; o servidor roda como uid 1000. Arquivo criado
    aqui sai root:root e o Minecraft não consegue nem criar o `session.lock`
    dentro do mundo — ele morre no boot com AccessDeniedException. O dono vem
    do próprio /data em vez de 1000 fixo, para seguir a imagem se ela mudar.
    """
    if os.name != "posix":
        return
    try:
        st = MC_DATA.stat()
        uid, gid = st.st_uid, st.st_gid
    except OSError:
        return
    targets = [path] + list(path.rglob("*")) if path.is_dir() else [path]
    for p in targets:
        try:
            os.chown(p, uid, gid)
        except OSError:
            pass


def dir_size(path: Path):
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def to_mb(value):
    """'3G' / '1500M' -> megabytes. None se não reconhecer."""
    if not value:
        return None
    m = re.fullmatch(r"(\d+)\s*([GgMm])", value.strip())
    if not m:
        return None
    n = int(m.group(1))
    return n * 1024 if m.group(2).lower() == "g" else n


def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def extract_world_zip(source, name):
    """Extrai um .zip de mundo. Aceita o level.dat na raiz ou numa pasta só.

    `source` é caminho em disco ou file-like. Mundo de verdade passa de 1 GB,
    então nada aqui pode carregar o arquivo inteiro na memória: o zipfile lê
    sob demanda e o staging fica no MESMO volume do destino, para o move final
    ser rename em vez de cópia de gigabytes.
    """
    dest = MC_DATA / name
    if dest.exists():
        abort(400, f"já existe um mundo chamado {name}")
    staging = MC_DATA / f".upload-{secrets.token_hex(4)}"
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(source) as zf:
            for member in zf.infolist():
                # Zip Slip: nome de membro com ../ ou caminho absoluto escaparia
                # do staging e escreveria em qualquer lugar do volume.
                target = (staging / member.filename).resolve()
                if staging.resolve() not in target.parents and target != staging.resolve():
                    raise ValueError(f"entrada suspeita no zip: {member.filename}")
            zf.extractall(staging)
        root = staging
        entries = [p for p in staging.iterdir() if not p.name.startswith("__MACOSX")]
        if not (root / "level.dat").exists() and len(entries) == 1 and entries[0].is_dir():
            root = entries[0]
        if not (root / "level.dat").exists():
            raise ValueError("o zip não contém level.dat — não parece um mundo")
        shutil.move(str(root), str(dest))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    # Sem isto o mundo fica root:root e o servidor não sobe.
    chown_like_data(dest)
    return dest


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------
# Estado das operações longas. Backup de 2 GB leva ~75 s e restauração ~105 s:
# sem porcentagem o usuário não sabe se travou.
TAREFAS_LONGAS = {}
_tl_lock = threading.Lock()


def job_set(nome, **campos):
    with _tl_lock:
        atual = TAREFAS_LONGAS.setdefault(nome, {})
        atual.update(campos)
        atual["em"] = now().strftime("%H:%M:%S")


def job_get(nome):
    with _tl_lock:
        return dict(TAREFAS_LONGAS.get(nome, {}))


def jobs_ativos():
    with _tl_lock:
        return {k: dict(v) for k, v in TAREFAS_LONGAS.items()
                if v.get("estado") in ("rodando",)}


def _acompanhar(nome, alvo_bytes, medir, parar):
    """Thread que estima a porcentagem enquanto o tar roda.

    O tar não reporta progresso. Comparar o que já saiu com o tamanho esperado
    dá um número honesto o bastante para a pessoa saber que está andando.
    """
    while not parar.is_set():
        try:
            atual = medir()
        except OSError:
            atual = 0
        pct = min(99, int(atual / alvo_bytes * 100)) if alvo_bytes else 0
        job_set(nome, pct=pct, feito=human_size(atual), total=human_size(alvo_bytes))
        print(f"[painel] {nome}: {pct}% — {human_size(atual)} de ~{human_size(alvo_bytes)}",
              flush=True)
        parar.wait(3)


def backup_now(label="manual"):
    """Congela o save antes de arquivar.

    Sem `save-off`/`save-all`, o tar pega o mundo no meio de uma escrita de
    região e o backup volta corrompido justamente no dia em que importa.
    """
    with _busy_lock:
        BACKUPS.mkdir(parents=True, exist_ok=True)
        running = container_state()["status"] == "running"
        if running:
            try_rcon("save-off")
            try_rcon("save-all flush")
            time.sleep(2)
        try:
            stamp = now().strftime("%Y-%m-%d_%H%M")
            path = BACKUPS / f"mc-{stamp}-{label}.tgz"
            # ~0.9 é a razão observada entre o .tgz e o /data cru neste mundo.
            alvo = int(dir_size(MC_DATA) * 0.9)
            job_set("backup", estado="rodando", pct=0, arquivo=path.name,
                    feito="0 B", total=human_size(alvo))
            parar = threading.Event()
            threading.Thread(target=_acompanhar, daemon=True, args=(
                "backup", alvo, lambda: path.stat().st_size if path.exists() else 0,
                parar)).start()
            try:
                code, _, err = run_cmd(
                    ["tar", "czf", str(path), "-C", str(MC_DATA), "."], timeout=3600)
            finally:
                parar.set()
            if code != 0:
                if path.exists():
                    path.unlink()
                job_set("backup", estado="falhou", erro=err.strip()[-300:])
                return False, err.strip()[-500:]
            job_set("backup", estado="pronto", pct=100,
                    feito=human_size(path.stat().st_size))
        finally:
            if running:
                try_rcon("save-on")

    st = load_state()
    prune_backups(st["backup"].get("keep", 7))
    remote = (st["backup"].get("remote") or "").strip()
    if remote:
        ok, msg = push_remote(path, remote)
        if not ok:
            return True, f"backup local ok, mas o envio falhou: {msg}"
    return True, path.name


def prune_backups(keep):
    files = sorted(BACKUPS.glob("mc-*.tgz"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[max(int(keep), 1):]:
        try:
            old.unlink()
        except OSError:
            pass


def push_remote(path, remote):
    env = dict(os.environ, RCLONE_CONFIG=str(RCLONE_CONF))
    try:
        p = subprocess.run(["rclone", "copy", str(path), remote, "--no-traverse"],
                           capture_output=True, text=True, timeout=7200, env=env)
    except subprocess.TimeoutExpired:
        return False, "rclone estourou o tempo limite"
    if p.returncode != 0:
        return False, (p.stderr or p.stdout).strip()[-500:]
    return True, "enviado"


def list_backups():
    if not BACKUPS.exists():
        return []
    out = []
    for p in sorted(BACKUPS.glob("mc-*.tgz"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = p.stat()
        out.append({
            "name": p.name,
            "size": human_size(stat.st_size),
            "at": datetime.fromtimestamp(stat.st_mtime, TZ).strftime("%d/%m/%Y %H:%M"),
        })
    return out


def restore_backup(name):
    """Para o servidor, limpa o /data e extrai. Destrutivo por natureza."""
    path = safe_path(BACKUPS, safe_name(name))
    if not path.exists():
        abort(404, "backup não encontrado")
    with _busy_lock:
        docker("stop", "-t", "60", CONTAINER, timeout=120)
        # Rede de segurança: o estado atual vira um .tgz antes de sumir.
        pre = BACKUPS / f"mc-{now():%Y-%m-%d_%H%M}-pre-restore.tgz"
        run_cmd(["tar", "czf", str(pre), "-C", str(MC_DATA), "."], timeout=3600)
        for child in MC_DATA.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except OSError:
                    pass
        alvo = int(path.stat().st_size / 0.9)
        job_set("restore", estado="rodando", pct=0, arquivo=path.name,
                feito="0 B", total=human_size(alvo))
        parar = threading.Event()
        threading.Thread(target=_acompanhar, daemon=True, args=(
            "restore", alvo, lambda: dir_size(MC_DATA), parar)).start()
        try:
            code, _, err = run_cmd(["tar", "xzf", str(path), "-C", str(MC_DATA)],
                                   timeout=3600)
        finally:
            parar.set()
        job_set("restore", estado="falhou" if code != 0 else "pronto",
                pct=100 if code == 0 else job_get("restore").get("pct", 0))
        # O tar devolve a posse gravada no arquivo. Backup feito antes da
        # correção de posse traria o mundo como root e o servidor não subiria.
        # Normalizar aqui torna o restore auto-corretivo, qualquer que seja a
        # idade do backup.
        chown_like_data(MC_DATA)
        docker("start", CONTAINER, timeout=120)
    if code != 0:
        return False, err.strip()[-500:]
    return True, f"restaurado de {name} (estado anterior salvo em {pre.name})"


# ---------------------------------------------------------------------------
# Agendador
# ---------------------------------------------------------------------------
_last_fired = {}


def due(key, hhmm, days):
    """True uma única vez por minuto agendado."""
    if not hhmm:
        return False
    t = now()
    if t.weekday() not in days:
        return False
    if t.strftime("%H:%M") != hhmm:
        return False
    stamp = t.strftime("%Y-%m-%d %H:%M")
    if _last_fired.get(key) == stamp:
        return False
    _last_fired[key] = stamp
    return True


# Último flush: monotonic (imune a ajuste de relógio) + o último erro já
# registrado, para não repetir a mesma linha no histórico a cada intervalo.
_last_flush = {"at": 0.0, "erro": ""}


def flush_do_mundo(avisar_s=FLUSH_AVISO_S, rcon=None, dormir=None):
    """Avisa quem está jogando, espera e grava. Devolve a resposta do save.

    `rcon` e `dormir` são injetáveis para o teste poder checar a ORDEM sem
    falar com servidor nenhum e sem esperar 10 s de verdade.
    """
    rcon = rcon or try_rcon
    dormir = dormir or time.sleep
    if avisar_s > 0:
        resp = rcon("say " + FLUSH_AVISO_MSG.format(s=avisar_s))
        # Servidor parado: não faz sentido esperar 10 s para falhar de novo.
        if resp.startswith("[rcon indisponível]"):
            return resp
        dormir(avisar_s)
    return rcon("save-all flush")


def paper_autosave_texto(texto, valor):
    """Troca só a linha `auto-save-interval:` do paper-world-defaults.yml.

    Sem parser de YAML de propósito: reescrever o arquivo com um parser mexeria
    em comentários, ordem e tipos de ~300 linhas que não são nossas. `valor` é
    um número de ticks ou a palavra "default".
    """
    # `.` nao casa newline sem DOTALL, entao `.*` para no fim da linha.
    novo, achou = re.subn(r"(?m)^(\s*auto-save-interval:).*",
                          lambda m: f"{m.group(1)} {valor}", texto, count=1)
    if achou != 1:
        raise ValueError("não achei a linha `auto-save-interval:` em "
                         + PAPER_WORLD_DEFAULTS)
    return novo


def paper_autosave_definir(valor):
    """Escreve o intervalo no config do Paper. Vale no próximo boot do servidor."""
    path = MC_DATA / PAPER_WORLD_DEFAULTS
    if not path.exists():
        return False, f"{PAPER_WORLD_DEFAULTS} não existe — suba o servidor uma vez."
    try:
        novo = paper_autosave_texto(path.read_text("utf-8", errors="replace"), valor)
    except (ValueError, OSError) as e:
        return False, str(e)
    try:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(novo, "utf-8")
        tmp.replace(path)
    except OSError as e:
        return False, f"não consegui escrever em {PAPER_WORLD_DEFAULTS}: {e}"
    return True, f"autosave do Paper: {valor}"


def flush_due(asv, last, mono):
    """True quando passou o intervalo configurado desde o último flush.

    Separado do loop porque é a única regra aqui que vale testar.
    """
    if not asv.get("enabled"):
        return False
    try:
        every = int(asv.get("every_min") or 5)
    except (TypeError, ValueError):
        every = 5
    every = max(1, min(120, every))
    return (mono - last) >= every * 60


def scheduler_loop():
    while True:
        try:
            st = load_state()
            sch, bkp = st["schedule"], st["backup"]
            days = sch.get("days") or list(range(7))
            if sch.get("enabled"):
                if due("start", sch.get("start_at"), days):
                    docker("start", CONTAINER, timeout=120)
                    log_system("agendador: servidor iniciado")
                if due("stop", sch.get("stop_at"), days):
                    try_rcon("say Servidor desligando em 30 segundos (agendado).")
                    time.sleep(30)
                    docker("stop", "-t", "60", CONTAINER, timeout=120)
                    log_system("agendador: servidor desligado")
                if due("restart", sch.get("restart_at"), days):
                    try_rcon("say Reiniciando em 30 segundos (agendado).")
                    time.sleep(30)
                    docker("restart", "-t", "60", CONTAINER, timeout=180)
                    log_system("agendador: servidor reiniciado")
            energia_retomar_se_passou()
            if bkp.get("enabled") and due("backup", bkp.get("at"), list(range(7))):
                ok, msg = backup_now("auto")
                log_system(f"agendador: backup {'ok' if ok else 'FALHOU'} — {msg}")
            if flush_due(st["autosave"], _last_flush["at"], time.monotonic()):
                _last_flush["at"] = time.monotonic()
                out = flush_do_mundo()
                # Sucesso não vira linha de histórico: a cada 2 min isso
                # apagaria o resto do log (200 entradas). Falha vira — mas só
                # uma vez por erro distinto, senão dá no mesmo.
                erro = out if out.startswith("[rcon indisponível]") else ""
                if erro and erro != _last_flush["erro"]:
                    log_system(f"agendador: flush do mundo falhou — {erro[:160]}")
                _last_flush["erro"] = erro
        except Exception as e:                      # thread nunca pode morrer
            log_system(f"agendador: erro inesperado — {e}")
        time.sleep(20)


def log_system(message):
    st = load_state()
    st["audit"].insert(0, {
        "at": now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": "agendador", "detail": message[:300], "user": "sistema",
    })
    del st["audit"][200:]
    save_state(st)
    print(f"[painel] {message}", flush=True)


# ---------------------------------------------------------------------------
# Rotas — autenticação
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        st = load_state()
        if check_password(request.form.get("password", ""), st.get("password")):
            session.clear()
            session["user"] = "admin"
            session.permanent = True
            return redirect(url_for("index"))
        time.sleep(1)       # desacelera tentativa em sequência
        error = "Senha incorreta."
    return render_template("login.html", error=error)


@app.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.post("/password")
@login_required
def change_password():
    atual = request.form.get("current", "")
    nova = request.form.get("new", "")
    st = load_state()
    if not check_password(atual, st.get("password")):
        return frag_error("Senha atual incorreta.")
    if len(nova) < 10:
        return frag_error("A senha nova precisa de pelo menos 10 caracteres.")
    st["password"] = hash_password(nova)
    save_state(st)
    audit("senha alterada")
    return frag_ok("Senha alterada.")


# ---------------------------------------------------------------------------
# Rotas — página
# ---------------------------------------------------------------------------
@app.get("/")
@login_required
def index():
    alvo = request.args.get("alvo", "minecraft")
    if alvo not in ALVOS:
        alvo = "minecraft"
    spec = ALVOS[alvo]
    aba = request.args.get("aba") or spec["abas"][0][0]
    if aba not in [a for a, _ in spec["abas"]]:
        aba = spec["abas"][0][0]
    # Tudo renderizado aqui: a tela chega pronta, sem dois saltos de HTMX
    # mostrando cartão vazio antes do conteúdo.
    return render_template(
        "app.html", csrf=csrf_token(), alvo=alvo, alvos=ALVOS,
        chave=alvo, spec=spec, aba=aba, cab=cabecalho(alvo),
        conteudo_html=render_aba(alvo, aba), atual=alvo,
        itens=[{"chave": k, "spec": v, "estado": estado_alvo(k)} for k, v in ALVOS.items()])


# ---------------------------------------------------------------------------
# Chrome: lateral, cabeçalho, abas
# ---------------------------------------------------------------------------
@app.get("/f/lateral")
@login_required
def f_lateral():
    itens = []
    for chave, spec in ALVOS.items():
        itens.append({"chave": chave, "spec": spec, "estado": estado_alvo(chave)})
    return render_template("_lateral.html", itens=itens,
                           atual=request.args.get("alvo", "minecraft"))


@app.get("/f/alvo/<chave>")
@login_required
def f_alvo(chave):
    if chave not in ALVOS:
        abort(404)
    spec = ALVOS[chave]
    aba = request.args.get("aba") or spec["abas"][0][0]
    if aba not in [a for a, _ in spec["abas"]]:
        aba = spec["abas"][0][0]
    return render_template("_alvo.html", chave=chave, spec=spec, aba=aba,
                           cab=cabecalho(chave))


def cabecalho(chave):
    """Dados do cabeçalho: nome, estado, e a faixa de recursos do alvo."""
    spec = ALVOS[chave]
    est = estado_alvo(chave)
    dados = {"estado": est, "linha": "", "recursos": []}
    if spec["tipo"] == "minecraft":
        cs = container_state()
        stats = container_stats()
        env = read_env()
        props = read_properties()
        dados["linha"] = f"Paper {props.get('level-name', '')}".strip()
        dados["uptime"] = cs["uptime"]
        dados["saude"] = cs["health"]
        # O terceiro item leva para a aba onde aquilo se muda. Na referência
        # esta faixa é a banda interativa (select de Java, stepper de RAM); aqui
        # ela é atalho em vez de controle duplicado, já que Configurações valida
        # cada campo e recria o container.
        dados["recursos"] = [
            ("Versão", env.get("MC_VERSION", "—"), "config"),
            ("Java", env.get("MC_JAVA", "—"), "config"),
            ("Memória", f"{env.get('MC_HEAP', '—')} de {env.get('MC_MEM_LIMIT', '—')}", "config"),
            ("Em uso", stats["mem"], None),
            ("CPU", stats["cpu"], None),
        ]
        bruto = try_rcon("list") if cs["status"] == "running" else ""
        # "There are 0 of a max of 4 players online:" não é frase para cabeçalho.
        m = re.search(r"(\d+)\s+of\s+a\s+max\s+of\s+(\d+)", bruto)
        dados["jogadores"] = (f"{m.group(1)} de {m.group(2)} jogadores" if m
                              else ("servidor parado" if not bruto else bruto))
    elif spec["tipo"] == "pilha":
        dados["linha"] = spec["sub"]
        dados["recursos"] = [
            ("Containers", f"{est['no_ar']} de {est['total']} no ar"),
            ("Projeto", spec["projeto"]),
        ]
        if spec.get("depende_de"):
            dados["recursos"].append(("Depende de", ALVOS[spec["depende_de"]]["label"]))
        if spec.get("exigido_por"):
            dados["recursos"].append(("Exigido por", ALVOS[spec["exigido_por"]]["label"]))
    else:
        info = host_info()
        e = energia_estado()
        dados["linha"] = info["host"]
        dados["energia"] = e
        dados["recursos"] = [
            ("No ar há", info["uptime"]), ("Memória", info["mem"]),
            ("Disco", info["disco"]), ("Carga", info["carga"]),
        ]
    return dados


def _uptime_pt(txt):
    """`uptime -p` fala inglês. Numa interface em português, "5 hours,
    43 minutes" é uma emenda visível."""
    for en, pt in (("weeks", "semanas"), ("week", "semana"), ("days", "dias"),
                   ("day", "dia"), ("hours", "horas"), ("hour", "hora"),
                   ("minutes", "minutos"), ("minute", "minuto")):
        txt = txt.replace(en, pt)
    return txt


def host_info():
    code, out, _ = host_run(
        "sh", "-c",
        "hostname; uptime -p; free -h | awk '/Mem:/{print $3\" de \"$2}'; "
        "df -h / | awk 'NR==2{print $4\" livres de \"$2}'; "
        "cut -d' ' -f1-3 /proc/loadavg", timeout=120)
    linhas = (out.strip().splitlines() + ["—"] * 5)[:5]
    return {"host": linhas[0], "uptime": _uptime_pt(linhas[1].replace("up ", "")),
            "mem": linhas[2], "disco": linhas[3], "carga": linhas[4],
            "ok": code == 0}


@app.get("/f/cabecalho/<chave>/<aba>")
@login_required
def f_cabecalho(chave, aba):
    if chave not in ALVOS:
        abort(404)
    spec = ALVOS[chave]
    if aba not in [a for a, _ in spec["abas"]]:
        aba = spec["abas"][0][0]
    return render_template("_cabecalho.html", chave=chave, spec=spec, aba=aba,
                           cab=cabecalho(chave))


@app.get("/f/aba/<chave>/<aba>")
@login_required
def f_aba(chave, aba):
    return render_aba(chave, aba)


def render_aba(chave, aba):
    """Corpo de uma aba. Função separada da rota para a primeira resposta do
    painel já sair com o conteúdo dentro, em vez de um "carregando…"."""
    if chave not in ALVOS:
        abort(404)
    spec = ALVOS[chave]
    if aba not in [a for a, _ in spec["abas"]]:
        abort(404)

    if spec["tipo"] == "pilha":
        est = estado_alvo(chave)
        if aba == "containers":
            return render_template("_pilha_containers.html", chave=chave,
                                   spec=spec, est=est)
        if aba == "console":
            alvo_log = request.args.get("container") or (
                est["containers"][0]["nome"] if est["containers"] else "")
            log = ""
            if alvo_log and any(c["nome"] == alvo_log for c in est["containers"]):
                _, o, e = docker("logs", "--tail", "300", alvo_log, timeout=30)
                log = (o + e)[-60000:]
            return render_template("_pilha_log.html", chave=chave, est=est,
                                   alvo_log=alvo_log, log=log)
        return render_template("_pilha_visao.html", chave=chave, spec=spec, est=est,
                               auto=autostart_estado(spec["projeto"]))

    if spec["tipo"] == "host":
        if aba == "tarefas":
            return render_template("_tarefas.html", t=tarefas())
        if aba == "energia":
            st = load_state()
            return render_template("_energia.html", e=energia_estado(),
                                   pular=st.get("energia_pular_ate", ""),
                                   hoje=now().strftime("%Y-%m-%d"))
        if aba == "historico":
            return render_template("_historico.html", audit=load_state()["audit"][:80])
        return render_template("_host_visao.html", info=host_info(),
                               alvos=[(k, ALVOS[k], estado_alvo(k))
                                      for k in ("minecraft", "igenda", "supabase")])

    # Minecraft
    if aba == "console":
        return render_template("_mc_console.html")
    if aba == "jogadores":
        return f_players()
    if aba == "conteudo":
        env = read_env()
        criar = []
        for chave, spec in CRIAR_CAMPOS.items():
            criar.append({"key": chave, "spec": spec,
                          "value": env.get(chave, "")})
        return render_template("_mc_conteudo.html", worlds=list_worlds(),
                               criar=criar)
    if aba == "automacao":
        st = load_state()
        return render_template("_mc_automacao.html", backups=list_backups(),
                               cfg=st["backup"], sch=st["schedule"],
                               asv=st["autosave"],
                               rclone_ok=RCLONE_CONF.exists(),
                               auto=autostart_estado("minecraft"))
    if aba == "config":
        return f_config()
    return render_template("_mc_visao.html", est=estado_alvo("minecraft"),
                           cs=container_state(), stats=container_stats(),
                           props=read_properties(),
                           online=try_rcon("list"),
                           backups=list_backups()[:3], worlds=list_worlds())


# ---------------------------------------------------------------------------
# Ações: pilhas, containers, energia
# ---------------------------------------------------------------------------
def exige_digitar(esperado):
    """Confirmação digitada para o que derruba produção.

    `window.confirm` cai com um Enter distraído. Digitar o nome do serviço é o
    degrau que separa "quase cliquei" de "eu quis". Devolve None quando passou.
    """
    dado = (request.headers.get("HX-Prompt") or "").strip()
    if dado.lower() != esperado.lower():
        return frag_error(
            f"Confirmação não bateu — nada foi feito. Para seguir, digite exatamente: {esperado}")
    return None


@app.post("/a/pilha/<chave>/<acao>")
@login_required
def a_pilha(chave, acao):
    if chave not in ALVOS or acao not in {"start", "stop", "restart"}:
        abort(400)
    spec = ALVOS[chave]
    if spec["tipo"] == "minecraft":
        return a_power({"start": "start", "stop": "stop", "restart": "restart"}[acao])
    if spec["tipo"] != "pilha":
        abort(400)
    if spec.get("risco") == "producao" and acao in ("stop", "restart"):
        barrado = exige_digitar(spec["label"])
        if barrado:
            return barrado
    ok, msg = pilha_acao(chave, acao)
    audit(f"pilha:{acao}", f"{chave} — {msg}")
    return frag_ok(msg) if ok else frag_error(msg)


@app.post("/a/container/<nome>/<acao>")
@login_required
def a_container(nome, acao):
    if acao not in {"start", "stop", "restart"}:
        abort(400)
    conhecidos = set()
    for chave, spec in ALVOS.items():
        if spec.get("projeto"):
            conhecidos |= {c["nome"] for c in project_containers(spec["projeto"])}
    if nome not in conhecidos:
        return frag_error("Container desconhecido.")
    args = ["stop", "-t", "30", nome] if acao == "stop" else [acao, nome]
    code, out, err = docker(*args, timeout=180)
    audit(f"container:{acao}", nome)
    return frag_ok(f"{nome}: {acao} ok.") if code == 0 else frag_error((err or out).strip()[-300:])


@app.post("/a/tudo/<acao>")
@login_required
def a_tudo(acao):
    if acao not in {"start", "stop"}:
        abort(400)
    if acao == "stop":
        barrado = exige_digitar("DESLIGAR TUDO")
        if barrado:
            return barrado
    ordem = ["supabase", "igenda", "minecraft"] if acao == "start" else \
            ["minecraft", "igenda", "supabase"]
    feitos = []
    for chave in ordem:
        spec = ALVOS[chave]
        if spec["tipo"] == "minecraft":
            args = ["stop", "-t", "60", CONTAINER] if acao == "stop" else [acao, CONTAINER]
            docker(*args, timeout=180)
            feitos.append(spec["label"])
        else:
            ok, _ = _agir_containers(spec["projeto"], acao)
            if ok:
                feitos.append(spec["label"])
    audit(f"tudo:{acao}", ", ".join(feitos))
    return frag_ok(("Ligando: " if acao == "start" else "Desligando: ") + " → ".join(feitos))


@app.get("/f/energia/estado")
@login_required
def f_energia_estado():
    st = load_state()
    return render_template("_energia_estado.html", e=energia_estado(),
                           pular=st.get("energia_pular_ate", ""),
                           hoje=now().strftime("%Y-%m-%d"))


@app.post("/a/autostart/<chave>")
@login_required
def a_autostart(chave):
    if chave not in ALVOS or not ALVOS[chave].get("projeto"):
        abort(400)
    ligado = request.form.get("ligado") == "1"
    ok, msg = autostart_definir(ALVOS[chave]["projeto"], ligado)
    audit("autostart", f"{chave}: {'liga' if ligado else 'não liga'} no boot")
    return frag_ok(msg) if ok else frag_error(msg)


@app.post("/a/energia/ligar")
@login_required
def a_energia_ligar():
    ligado = request.form.get("ligado") == "1"
    ok, msg = energia_ligar(ligado)
    audit("energia", msg)
    return frag_ok(msg) if ok else frag_error(msg)


@app.post("/a/energia/horarios")
@login_required
def a_energia_horarios():
    agenda = {}
    for n in range(1, 8):
        agenda[n] = {
            "acorda": valid_hhmm(request.form.get(f"acorda_{n}"), DIA_PADRAO["acorda"]),
            "dorme": valid_hhmm(request.form.get(f"dorme_{n}"), DIA_PADRAO["dorme"]),
            "liga_acorda": bool(request.form.get(f"liga_acorda_{n}")),
            "liga_dorme": bool(request.form.get(f"liga_dorme_{n}")),
        }
    ok, msg = energia_definir_agenda(agenda)
    resumo = " ".join(
        f"{DIAS_SEMANA[n - 1]} "
        f"{d['acorda'] if d['liga_acorda'] else '—'}/{d['dorme'] if d['liga_dorme'] else '—'}"
        for n, d in agenda.items())
    audit("energia:agenda", resumo)
    return frag_ok(msg) if ok else frag_error(msg)


@app.post("/a/energia/pular")
@login_required
def a_energia_pular():
    ok, msg = energia_pular_noite()
    audit("energia:pular", msg)
    return frag_ok(msg) if ok else frag_error(msg)


@app.post("/a/energia/dormir-agora")
@login_required
def a_energia_dormir_agora():
    """Roda o mesmo script do agendamento: desliga e deixa o despertador do RTC
    armado. A máquina volta sozinha no horário de acordar."""
    barrado = exige_digitar("DESLIGAR")
    if barrado:
        return barrado
    e = energia_estado()
    audit("energia:dormir agora", f"acorda {e.get('acorda_agora')}")
    # Sem aviso no chat: quem clicou aqui já decidiu.
    code, out, err = host_run("systemd-run", "--on-active=5", "--unit=painel-dormir",
                              "--setenv=AVISO_MIN=0",
                              HOST_SCRIPT, timeout=120)
    if code != 0:
        return frag_error((err or out).strip()[-300:])
    return frag_ok(f"Desligando em 5 segundos. A máquina acorda {e.get('acorda_agora')}.")


def frag_ok(msg):
    """Sucesso dispara `panel-refresh`: os fragmentos escutam e se recarregam.

    Evita polling em listas onde o polling atrapalha (navegação de arquivos,
    formulário sendo preenchido) sem precisar de estado no cliente.
    """
    r = Response(render_template("_flash.html", kind="ok", msg=msg))
    r.headers["HX-Trigger"] = "panel-refresh"
    return r


def frag_error(msg):
    return render_template("_flash.html", kind="err", msg=msg)


# ---------------------------------------------------------------------------
# Rotas — fragmentos HTMX
# ---------------------------------------------------------------------------
@app.get("/f/console")
@login_required
def f_console():
    tail = request.args.get("tail", "200")
    tail = tail if tail.isdigit() else "200"
    _, out, err = docker("logs", "--tail", str(int(tail) * 3), CONTAINER, timeout=30)
    bruto = [ANSI_RE.sub("", l) for l in (out + err).splitlines()]
    # Ruído de conexão do RCON: a linha "Thread RCON Client" e a linha de
    # prompt ">...." que o Paper imprime junto. A conexão agora é persistente,
    # então isto só limpa o que ficou no histórico do log.
    limpo = []
    for l in bruto:
        l = PROMPT_PREFIXO.sub("", l, count=1)
        if not l.strip() or PROMPT_RE.match(l) or "Thread RCON Client" in l:
            continue
        limpo.append(l)
    juntas = chr(10).join(limpo[-int(tail):])
    return render_template("_console.html", log=juntas[-60000:],
                           ocultas=len(bruto) - len(limpo))


def _json_de(nome):
    path = MC_DATA / nome
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text("utf-8") or "[]")
    except json.JSONDecodeError:
        return []


@app.get("/f/players")
@login_required
def f_players():
    return render_template("_players.html",
                           j=jogadores_online(),
                           ops=_json_de("ops.json"),
                           whitelist=_json_de("whitelist.json"),
                           banned=_json_de("banned-players.json"),
                           wl_on=read_properties().get("white-list") == "true")


@app.get("/f/online")
@login_required
def f_online():
    """Só a lista de quem está online. Fragmento separado para poder atualizar
    sozinho sem apagar o que o usuário está digitando no formulário ao lado."""
    return render_template("_online.html", j=jogadores_online())


@app.get("/f/files")
@login_required
def f_files():
    rel = request.args.get("path", "")
    target = safe_path(MC_DATA, rel)
    if not target.exists():
        abort(404)
    entries = []
    for p in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        try:
            size = "-" if p.is_dir() else human_size(p.stat().st_size)
        except OSError:
            size = "?"
        entries.append({
            "name": p.name,
            "dir": p.is_dir(),
            "size": size,
            "rel": str(p.relative_to(MC_DATA)).replace("\\", "/"),
            "editable": p.is_file() and p.suffix.lower() in TEXT_SUFFIXES,
        })
    parent = "" if target == MC_DATA.resolve() else str(
        target.parent.relative_to(MC_DATA)).replace("\\", "/")
    return render_template("_files.html", entries=entries, cwd=rel,
                           parent=("" if rel == "" else parent), at_root=(rel == ""))


@app.get("/f/config")
@login_required
def f_config():
    env = read_env()
    worlds = [w["name"] for w in list_worlds()]
    campos = []
    for key, spec in FIELDS.items():
        atual = env.get(key, "")
        opcoes = worlds if spec["type"] == "worlds" else spec.get("options", [])
        # Valor que já está no .env mas saiu da lista (editado na mão, versão
        # antiga): entra como opção para não sumir calado do formulário.
        if atual and spec["type"] in ("select", "worlds") and atual not in opcoes:
            opcoes = [atual] + list(opcoes)
        campos.append({"key": key, "spec": spec, "value": atual, "options": opcoes})
    return render_template("_config.html", campos=campos, props=read_properties(),
                           tem_icone=(MC_DATA / ICON_PATH_NAME).exists())


@app.get("/a/icon/current")
@login_required
def a_icon_current():
    path = MC_DATA / ICON_PATH_NAME
    if not path.exists():
        abort(404)
    # no-store: sem isto o browser mostra o ícone antigo depois de trocar.
    return send_file(path, mimetype="image/png", max_age=0)


@app.post("/a/icon")
@login_required
def a_icon():
    f = request.files.get("file")
    if not f or not f.filename:
        return frag_error("Escolha uma imagem.")
    data = f.read(MAX_ICON_BYTES + 1)
    if len(data) > MAX_ICON_BYTES:
        return frag_error("Imagem grande demais (máximo 12 MB).")
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        return frag_error("Pillow não instalado na imagem do painel.")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError):
        return frag_error("Não consegui ler essa imagem. Use PNG, JPG ou WebP.")

    # O Minecraft exige 64x64 exato e ignora em silêncio qualquer outra coisa.
    # Recorta no centro para não achatar a imagem, depois reduz.
    img = img.convert("RGBA")
    lado = min(img.size)
    esq, topo = (img.width - lado) // 2, (img.height - lado) // 2
    img = img.crop((esq, topo, esq + lado, topo + lado)).resize(ICON_SIZE, Image.LANCZOS)

    destino = MC_DATA / ICON_PATH_NAME
    img.save(destino, "PNG")
    chown_like_data(destino)
    audit("ícone trocado", f.filename)
    return frag_ok("Ícone salvo. Reinicie o servidor para ele aparecer na lista.")


@app.post("/a/icon/delete")
@login_required
def a_icon_delete():
    (MC_DATA / ICON_PATH_NAME).unlink(missing_ok=True)
    audit("ícone removido")
    return frag_ok("Ícone removido. Reinicie o servidor para aplicar.")


# ---------------------------------------------------------------------------
# Rotas — ações
# ---------------------------------------------------------------------------
@app.post("/a/power/<action>")
@login_required
def a_power(action):
    if action not in {"start", "stop", "restart"}:
        abort(400)
    if action in {"stop", "restart"} and container_state()["status"] == "running":
        try_rcon("say Servidor sendo desligado pelo painel.")
        try_rcon("save-all flush")
    args = {"start": ["start", CONTAINER],
            "stop": ["stop", "-t", "60", CONTAINER],
            "restart": ["restart", "-t", "60", CONTAINER]}[action]
    code, out, err = docker(*args, timeout=180)
    audit(f"power:{action}", (err or out).strip())
    return frag_ok(f"{action} ok.") if code == 0 else frag_error((err or out).strip()[-300:])


@app.post("/a/rcon")
@login_required
def a_rcon():
    cmd = (request.form.get("cmd") or "").strip()
    if not cmd:
        return frag_error("Comando vazio.")
    try:
        out = rcon(cmd)
    except Exception as e:
        return frag_error(str(e))
    audit("rcon", cmd)
    return render_template("_rcon_out.html", cmd=cmd, out=out or "(sem resposta)")


@app.post("/a/player")
@login_required
def a_player():
    action = request.form.get("action", "")
    player = (request.form.get("player") or "").strip()
    simple = {"whitelist_on": "whitelist on", "whitelist_off": "whitelist off",
              "reload_whitelist": "whitelist reload"}
    if action in simple:
        cmd = simple[action]
    else:
        if not re.fullmatch(r"[A-Za-z0-9_]{1,16}", player):
            return frag_error("Nick inválido (até 16 caracteres, letras, números ou _).")
        table = {
            "op": f"op {player}", "deop": f"deop {player}",
            "whitelist_add": f"whitelist add {player}",
            "whitelist_remove": f"whitelist remove {player}",
            "kick": f"kick {player}", "ban": f"ban {player}", "pardon": f"pardon {player}",
        }
        if action not in table:
            abort(400)
        cmd = table[action]
    try:
        out = rcon(cmd)
    except Exception as e:
        return frag_error(str(e))
    audit("player", cmd)
    return frag_ok(out or f"{cmd} ok.")


@app.post("/a/world/upload")
@login_required
def a_world_upload():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".zip"):
        return frag_error("Envie um arquivo .zip.")
    name = safe_name(request.form.get("name") or Path(f.filename).stem)
    if (MC_DATA / name).exists():
        return frag_error(f"Já existe um mundo chamado '{name}'.")

    # `f.save()` copia em blocos. Um `f.read()` aqui traria 1,8 GB para a RAM
    # de um container limitado a 512M — era esse o bug que engolia o upload.
    # O arquivo vai para o próprio volume: mesmo sistema de arquivos do
    # destino, e espaço de sobra (o container tem pouca RAM, não pouco disco).
    tmp = MC_DATA / f".upload-{secrets.token_hex(4)}.zip"
    try:
        f.save(str(tmp))
        extract_world_zip(tmp, name)
    except (zipfile.BadZipFile, ValueError) as e:
        return frag_error(str(e))
    except OSError as e:
        return frag_error(f"erro de disco: {e}")
    finally:
        tmp.unlink(missing_ok=True)
    audit("mundo enviado", f"{name} ({human_size(dir_size(MC_DATA / name))})")
    return frag_ok(f"Mundo '{name}' recebido. Ative na lista para usar.")


@app.post("/a/world/create")
@login_required
def a_world_create():
    """Cria um mundo deixando o SERVIDOR gerar.

    Não há geração aqui dentro: escrevemos os parâmetros no .env, apontamos
    MC_LEVEL para o nome novo e recriamos o container. O Paper vê uma pasta que
    não existe e gera o mundo no boot, que é como o jogo faz.
    """
    nome = safe_name(request.form.get("nome"))
    if (MC_DATA / nome).exists():
        return frag_error(f"Já existe um mundo chamado '{nome}'. Escolha outro nome.")

    updates = {"MC_LEVEL": nome}
    for chave in CRIAR_CAMPOS:
        # Todo campo é escrito, mesmo em branco. Deixar de fora faria a semente
        # do mundo anterior vazar para o próximo que fosse criado.
        ok, erro = validate_field(chave, request.form.get(chave, ""), CRIAR_CAMPOS)
        if erro:
            return frag_error(erro)
        updates[chave] = ok

    if updates.get("MC_HARDCORE") == "true" and updates.get("MC_DIFFICULTY") != "hard":
        # O jogo força isso de qualquer jeito; melhor o painel dizer antes do
        # que o usuário descobrir pela dificuldade "errada" dentro do jogo.
        updates["MC_DIFFICULTY"] = "hard"

    write_env(updates)
    ok, msg = apply_config()
    audit("mundo criado", f"{nome} — " + ", ".join(
        f"{k.replace('MC_', '').lower()}={v}" for k, v in updates.items()
        if k != "MC_LEVEL" and v))
    if not ok:
        return frag_error(msg)
    semente = updates.get("MC_SEED") or "aleatória"
    return frag_ok(f"Mundo '{nome}' sendo gerado (semente: {semente}). "
                   "A geração leva de alguns segundos a alguns minutos; o "
                   "cabeçalho mostra 'no ar' quando terminar.")


@app.post("/a/world/activate")
@login_required
def a_world_activate():
    name = safe_name(request.form.get("name"))
    if not (MC_DATA / name / "level.dat").exists():
        return frag_error("Mundo não encontrado.")
    write_env({"MC_LEVEL": name})
    ok, msg = apply_config()
    audit("mundo ativado", name)
    return frag_ok(f"'{name}' ativo. Container recriado.") if ok else frag_error(msg)


@app.post("/a/world/delete")
@login_required
def a_world_delete():
    name = safe_name(request.form.get("name"))
    if name == read_properties().get("level-name", "world"):
        return frag_error("Não dá para apagar o mundo ativo. Ative outro antes.")
    target = safe_path(MC_DATA, name)
    if not (target / "level.dat").exists():
        return frag_error("Mundo não encontrado.")
    shutil.rmtree(target, ignore_errors=True)
    audit("mundo apagado", name)
    return frag_ok(f"Mundo '{name}' apagado.")


@app.get("/a/world/download")
@login_required
def a_world_download():
    """Compacta em disco, não na memória.

    Um mundo passa de 2 GB. Montar o zip num BytesIO estouraria o limite de
    512M do container — o mesmo erro que engolia o upload, na direção inversa.
    """
    name = safe_name(request.args.get("name"))
    target = safe_path(MC_DATA, name)
    if not (target / "level.dat").exists():
        abort(404)
    tmp = MC_DATA / f".download-{secrets.token_hex(4)}.zip"
    # ZIP_STORED: região de mundo já é comprimida. Deflate gastaria minutos de
    # CPU — disputada com o servidor — para economizar pouco.
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
        for p in target.rglob("*"):
            if p.is_file() and p.name != "session.lock":
                zf.write(p, p.relative_to(target.parent))
        # Paper 26.x grava world_gen_settings/game_rules/... só dentro de
        # dimensions/minecraft/overworld/data/minecraft; o singleplayer vanilla
        # lê da raiz data/minecraft e, sem eles, recusa o mundo como
        # "dados inválidos ou corrompidos". Copia para a raiz no zip.
        raiz = target / "data" / "minecraft"
        over = target / "dimensions" / "minecraft" / "overworld" / "data" / "minecraft"
        for f in ("world_gen_settings", "game_rules", "weather",
                  "scheduled_events", "wandering_trader"):
            src = over / f"{f}.dat"
            if src.is_file() and not (raiz / f"{f}.dat").exists():
                zf.write(src, (raiz / f"{f}.dat").relative_to(target.parent))

    @after_this_request
    def cleanup(response):
        tmp.unlink(missing_ok=True)
        return response

    return send_file(tmp, mimetype="application/zip",
                     as_attachment=True, download_name=f"{name}.zip")


def _em_segundo_plano(nome, alvo, *args):
    """Dispara a operação longa numa thread e volta na hora.

    Segurar a requisição por 105 segundos faz o navegador parecer travado e
    convida o usuário a clicar de novo.
    """
    if job_get(nome).get("estado") == "rodando":
        return False, "Já existe uma operação desse tipo em andamento."

    def correr():
        try:
            ok, msg = alvo(*args)
            job_set(nome, estado="pronto" if ok else "falhou", mensagem=msg)
            log_system(f"{nome}: {'ok' if ok else 'FALHOU'} — {msg}")
        except Exception as e:
            job_set(nome, estado="falhou", mensagem=str(e))
            log_system(f"{nome}: erro — {e}")

    job_set(nome, estado="rodando", pct=0, mensagem="", erro="")
    threading.Thread(target=correr, daemon=True).start()
    return True, "iniciado"


@app.post("/a/backup/run")
@login_required
def a_backup_run():
    ok, msg = _em_segundo_plano("backup", backup_now, "manual")
    if not ok:
        return frag_error(msg)
    audit("backup manual", "iniciado")
    return frag_ok("Backup começou. O progresso aparece abaixo.")


@app.get("/f/job")
@login_required
def f_job():
    return render_template("_job.html", backup=job_get("backup"),
                           restore=job_get("restore"))


@app.post("/a/backup/config")
@login_required
def a_backup_config():
    st = load_state()
    st["backup"] = {
        "enabled": request.form.get("enabled") == "on",
        "at": valid_hhmm(request.form.get("at"), "04:00"),
        "keep": max(1, min(365, int(request.form.get("keep") or 7))),
        "remote": (request.form.get("remote") or "").strip()[:120],
    }
    save_state(st)
    audit("backup configurado", json.dumps(st["backup"]))
    return frag_ok("Backup configurado.")


@app.post("/a/backup/restore")
@login_required
def a_backup_restore():
    nome = safe_name(request.form.get("name"))
    if not (BACKUPS / nome).exists():
        return frag_error("Backup não encontrado.")
    ok, msg = _em_segundo_plano("restore", restore_backup, nome)
    if not ok:
        return frag_error(msg)
    audit("restore", f"iniciado de {nome}")
    return frag_ok("Restauração começou. O servidor para e volta sozinho ao fim.")


@app.post("/a/backup/delete")
@login_required
def a_backup_delete():
    nomes = request.form.getlist("name") or []
    if not nomes:
        return frag_error("Nenhum backup selecionado.")
    apagados, falhas = [], []
    for bruto in nomes:
        try:
            path = safe_path(BACKUPS, safe_name(bruto))
        except Exception:
            falhas.append(bruto)
            continue
        if path.exists():
            try:
                path.unlink()
                apagados.append(path.name)
            except OSError as e:
                falhas.append(f"{path.name} ({e})")
    audit("backup apagado", ", ".join(apagados))
    if falhas and not apagados:
        return frag_error("Nada apagado: " + ", ".join(falhas))
    recado = f"{len(apagados)} backup(s) apagado(s)."
    if falhas:
        recado += " Falhou em: " + ", ".join(falhas)
    return frag_ok(recado)


@app.get("/a/backup/download")
@login_required
def a_backup_download():
    path = safe_path(BACKUPS, safe_name(request.args.get("name")))
    if not path.exists():
        abort(404)
    return send_file(path, mimetype="application/gzip",
                     as_attachment=True, download_name=path.name,
                     conditional=True)


@app.post("/a/rclone")
@login_required
def a_rclone():
    """Recebe o rclone.conf gerado pelo `rclone config` no PC do usuário.

    O fluxo OAuth do Google abre navegador e não roda dentro do container —
    por isso o arquivo vem pronto em vez de configurar aqui.
    """
    f = request.files.get("file")
    if not f:
        return frag_error("Selecione o arquivo rclone.conf.")
    data = f.read(256 * 1024)
    if b"[" not in data:
        return frag_error("Isso não parece um rclone.conf.")
    PANEL_DATA.mkdir(parents=True, exist_ok=True)
    RCLONE_CONF.write_bytes(data)
    RCLONE_CONF.chmod(0o600)
    audit("rclone.conf enviado")
    return frag_ok("rclone.conf salvo. Agora preencha o destino, ex.: gdrive:minecraft")


@app.post("/a/rclone/test")
@login_required
def a_rclone_test():
    remote = (request.form.get("remote") or "").strip()
    if not remote:
        return frag_error("Informe o destino primeiro.")
    env = dict(os.environ, RCLONE_CONFIG=str(RCLONE_CONF))
    p = subprocess.run(["rclone", "lsd", remote], capture_output=True, text=True,
                       timeout=120, env=env)
    if p.returncode != 0:
        return frag_error((p.stderr or p.stdout).strip()[-400:])
    return frag_ok("Destino acessível.")


@app.post("/a/file/save")
@login_required
def a_file_save():
    target = safe_path(MC_DATA, request.form.get("path", ""))
    if not target.is_file():
        abort(404)
    target.write_text(request.form.get("content", ""), "utf-8")
    audit("arquivo editado", str(target.relative_to(MC_DATA)))
    return frag_ok("Salvo. Reinicie o servidor para aplicar.")


@app.get("/a/file/open")
@login_required
def a_file_open():
    target = safe_path(MC_DATA, request.args.get("path", ""))
    if not target.is_file():
        abort(404)
    if target.stat().st_size > MAX_EDIT_BYTES:
        return frag_error("Arquivo grande demais para o editor. Baixe em vez de editar.")
    return render_template("_editor.html",
                           path=str(target.relative_to(MC_DATA)).replace("\\", "/"),
                           content=target.read_text("utf-8", errors="replace"))


@app.get("/a/file/download")
@login_required
def a_file_download():
    target = safe_path(MC_DATA, request.args.get("path", ""))
    if not target.is_file():
        abort(404)
    return send_file(target, as_attachment=True, download_name=target.name)


@app.post("/a/file/upload")
@login_required
def a_file_upload():
    folder = safe_path(MC_DATA, request.form.get("path", ""))
    f = request.files.get("file")
    if not f or not f.filename:
        return frag_error("Nenhum arquivo.")
    dest = folder / safe_name(Path(f.filename).name)
    f.save(str(dest))          # em blocos: um .jar de mod passa de 100 MB
    chown_like_data(dest)      # senão o servidor não consegue ler o plugin
    audit("arquivo enviado", f.filename)
    return frag_ok("Arquivo enviado.")


@app.post("/a/file/delete")
@login_required
def a_file_delete():
    target = safe_path(MC_DATA, request.form.get("path", ""))
    if target == MC_DATA.resolve():
        abort(400)
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    elif target.exists():
        target.unlink()
    audit("arquivo apagado", request.form.get("path", ""))
    return frag_ok("Apagado.")


def validate_field(key, value, specs=None):
    """Devolve (valor_ok, erro). O domínio do campo é lei no servidor.

    A interface manda select e campo numérico, mas quem decide é aqui: um POST
    forjado não pode escrever qualquer coisa no .env do container.
    """
    spec = (specs or FIELDS)[key]
    value = (value or "").strip()
    kind = spec["type"]

    if kind == "select":
        if value not in spec["options"]:
            return None, f"{spec['label']}: '{value}' não é uma opção válida."
        return value, None

    if kind == "worlds":
        nomes = [w["name"] for w in list_worlds()]
        if value not in nomes:
            return None, f"{spec['label']}: mundo '{value}' não existe."
        return value, None

    if kind == "number":
        # O limite de dígitos é só uma trava contra entrada absurda antes do
        # int(); quem decide a faixa é o min/max logo abaixo. Em 6 dígitos ele
        # recusava o próprio default do raio do mundo (29999984, oito dígitos).
        if not re.fullmatch(r"-?\d{1,10}", value):
            return None, f"{spec['label']}: precisa ser um número inteiro."
        n = int(value)
        if not (spec["min"] <= n <= spec["max"]):
            return None, (f"{spec['label']}: use entre {spec['min']} e {spec['max']} "
                          f"(recebi {n}).")
        return str(n), None

    if not re.fullmatch(spec["pattern"], value):
        return None, f"{spec['label']}: formato inválido."
    return value, None


@app.post("/a/config")
@login_required
def a_config():
    updates = {}
    for key, value in request.form.items():
        if key == "csrf":
            continue
        if key not in EDITABLE_ENV or not ENV_KEY_RE.match(key):
            continue
        ok, erro = validate_field(key, value)
        if erro:
            return frag_error(erro)
        updates[key] = ok
    if not updates:
        return frag_error("Nada para salvar.")
    # Erro clássico e silencioso: heap igual (ou acima) do teto do cgroup faz o
    # kernel matar a JVM na primeira GC pesada. Barrar aqui é mais barato que
    # descobrir pelo container em loop de restart.
    heap, teto = to_mb(updates.get("MC_HEAP")), to_mb(updates.get("MC_MEM_LIMIT"))
    if heap and teto and heap > teto - 1024:
        return frag_error(
            f"Memória da JVM ({updates['MC_HEAP']}) precisa ficar pelo menos 1 G "
            f"abaixo do limite do container ({updates['MC_MEM_LIMIT']}). "
            "Senão o container morre por OOM na primeira coleta de lixo pesada.")
    write_env(updates)
    ok, msg = apply_config()
    audit("config aplicada", ", ".join(f"{k}={v}" for k, v in updates.items()))
    return frag_ok("Configuração aplicada e container recriado.") if ok else frag_error(msg)


@app.post("/a/schedule")
@login_required
def a_schedule():
    st = load_state()
    days = [int(d) for d in request.form.getlist("days") if d.isdigit() and 0 <= int(d) <= 6]
    st["schedule"] = {
        "enabled": request.form.get("enabled") == "on",
        "start_at": valid_hhmm(request.form.get("start_at"), ""),
        "stop_at": valid_hhmm(request.form.get("stop_at"), ""),
        "restart_at": valid_hhmm(request.form.get("restart_at"), ""),
        "days": days or list(range(7)),
    }
    save_state(st)
    audit("agendamento salvo", json.dumps(st["schedule"]))
    return frag_ok("Agendamento salvo.")


@app.post("/a/autosave")
@login_required
def a_autosave():
    st = load_state()
    st["autosave"] = {
        "enabled": request.form.get("enabled") == "on",
        "every_min": valid_int(request.form.get("every_min"), 5, 1, 120),
    }
    save_state(st)
    audit("flush do mundo configurado", json.dumps(st["autosave"]))
    # Com o painel gravando e avisando antes, o autosave do Paper viraria uma
    # travada sem aviso no meio — não existe como anunciar o save dele, então
    # o jeito de avisar de TODOS é o painel ser quem grava.
    alvo = PAPER_AUTOSAVE_TICKS if st["autosave"]["enabled"] else "default"
    ok, detalhe = paper_autosave_definir(alvo)
    aviso = ("" if ok else f" Atenção: {detalhe}")
    return frag_ok(f"Flush do mundo salvo. Aviso de {FLUSH_AVISO_S}s ligado. "
                   f"O autosave próprio do Paper ({detalhe}) só muda no "
                   f"próximo reinício do servidor.{aviso}")


def valid_int(value, fallback, lo, hi):
    value = (value or "").strip()
    try:
        n = int(value) if value else fallback
    except ValueError:
        abort(400, "número inválido")
    return max(lo, min(hi, n))


def valid_hhmm(value, fallback):
    value = (value or "").strip()
    if not value:
        return fallback
    if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
        return value
    abort(400, "horário inválido (use HH:MM)")


# ---------------------------------------------------------------------------
# Início
# ---------------------------------------------------------------------------
def create_app():
    PANEL_DATA.mkdir(parents=True, exist_ok=True)
    BACKUPS.mkdir(parents=True, exist_ok=True)
    # O Werkzeug bufferiza upload grande em arquivo temporário. Apontando o
    # TMPDIR para o volume, 1,8 GB de mundo não incham a camada do container.
    tmpdir = MC_DATA / ".tmp"
    try:
        tmpdir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("TMPDIR", str(tmpdir))
    except OSError:
        pass
    generated = ensure_password()
    if generated:
        print("=" * 68, flush=True)
        print("  PAINEL: senha inicial gerada (aparece só uma vez)", flush=True)
        print(f"  senha: {generated}", flush=True)
        print("  Troque na aba Configuração depois de entrar.", flush=True)
        print("=" * 68, flush=True)
    app.secret_key = load_state()["secret_key"]
    app.permanent_session_lifetime = timedelta(days=7)
    return app


if __name__ == "__main__":
    create_app()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    # Waitress no lugar do servidor de desenvolvimento do Flask. O dev server
    # engasga transferindo gigabytes enquanto atende o polling do painel — era
    # ele que fazia o download de backup de 2,3 GB falhar no navegador.
    from waitress import serve
    serve(app, host="0.0.0.0", port=8080, threads=8,
          # Upload de mundo passa de 1 GB e leva minutos; o padrão de 2 min
          # derrubaria a conexão no meio.
          channel_timeout=7200, cleanup_interval=60,
          max_request_body_size=5 * 1024 * 1024 * 1024,
          ident="painel")
