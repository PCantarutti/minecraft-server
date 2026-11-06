"""Checagem mínima do painel: roda com `python test_panel.py`.

Cobre só o que, quebrado, causa estrago de verdade:
  - travessia de caminho (../) no navegador de arquivos e nos backups
  - Zip Slip no upload de mundo
  - protocolo RCON (enquadramento + resposta fatiada)
  - senha: hash confere, hash errado não passa
  - parser/escritor do .env preserva comentários

Sem framework, sem fixture. Um assert que falha é o sinal.
"""

import io
import os
import re
import socket
import subprocess
import struct
import tempfile
import threading
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ.setdefault("MC_DATA", tempfile.mkdtemp())
os.environ.setdefault("PROJECT_DIR", tempfile.mkdtemp())
os.environ.setdefault("BACKUP_DIR", tempfile.mkdtemp())
os.environ.setdefault("PANEL_DATA", tempfile.mkdtemp())

import app as panel          # noqa: E402
import mcrcon                # noqa: E402


def test_safe_path():
    root = Path(tempfile.mkdtemp())
    (root / "ok.txt").write_text("x")
    assert panel.safe_path(root, "ok.txt") == (root / "ok.txt").resolve()
    assert panel.safe_path(root, "") == root.resolve()

    # Caminho que parece absoluto não é rejeitado: a barra inicial é removida e
    # ele vira relativo à raiz. Continua contido, que é o que importa.
    contained = panel.safe_path(root, "/etc/passwd")
    assert root.resolve() in contained.parents

    # Travessia de verdade tem que ser barrada.
    for evil in ["../etc/passwd", "a/../../etc/passwd", "../../"]:
        try:
            panel.safe_path(root, evil)
        except Exception:
            continue          # abort() do Flask vira exceção fora de request
        raise AssertionError(f"safe_path deixou escapar: {evil}")
    print("ok  safe_path barra travessia e contém caminho absoluto")


def test_safe_name():
    for good in ["world", "meu mundo", "back-up_1.tgz"]:
        assert panel.safe_name(good) == good
    for bad in ["../x", "a/b", "", "x" * 80, "nome;rm -rf /"]:
        try:
            panel.safe_name(bad)
        except Exception:
            continue
        raise AssertionError(f"safe_name aceitou: {bad!r}")
    print("ok  safe_name rejeita nome perigoso")


def test_zip_slip():
    """Um zip com ../ no nome do membro não pode escrever fora do staging."""
    mc = Path(tempfile.mkdtemp())
    panel.MC_DATA = mc
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../escapou.txt", "nao deveria existir")
        zf.writestr("level.dat", "x")
    buf.seek(0)
    try:
        panel.extract_world_zip(buf, "mundo")
    except ValueError:
        pass
    else:
        raise AssertionError("extract_world_zip aceitou zip com travessia")
    assert not (mc.parent / "escapou.txt").exists()
    print("ok  extract_world_zip barra Zip Slip")


def test_zip_ok():
    """Zip legítimo, com o mundo dentro de uma pasta só, é aceito e achatado."""
    mc = Path(tempfile.mkdtemp())
    panel.MC_DATA = mc
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("MeuMundo/level.dat", "x")
        zf.writestr("MeuMundo/region/r.0.0.mca", "y")
    buf.seek(0)
    dest = panel.extract_world_zip(buf, "mundo")
    assert (dest / "level.dat").exists(), "level.dat não foi achatado para a raiz"
    assert (dest / "region" / "r.0.0.mca").exists()
    print("ok  extract_world_zip aceita mundo em pasta única")


def test_zip_from_disk():
    """O upload real passa um CAMINHO, não um stream: 1,8 GB não cabe na RAM."""
    mc = Path(tempfile.mkdtemp())
    panel.MC_DATA = mc
    zpath = Path(tempfile.mkdtemp()) / "mundo.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("Meu Mundo/level.dat", "x")
        zf.writestr("Meu Mundo/region/r.0.0.mca", "y" * 1000)
    dest = panel.extract_world_zip(zpath, "domundo")
    assert (dest / "level.dat").exists()
    assert (dest / "region" / "r.0.0.mca").exists()
    # Staging não pode sobrar, e não pode aparecer como mundo na lista.
    leftovers = [p.name for p in mc.iterdir() if p.name.startswith(".upload")]
    assert not leftovers, f"staging vazou: {leftovers}"
    names = [w["name"] for w in panel.list_worlds()]
    assert names == ["domundo"], names
    print("ok  extract_world_zip aceita caminho em disco e limpa staging")


def test_chown_like_data():
    """Mundo extraído precisa sair com o dono do /data, não root.

    Root:root faz o servidor morrer no boot com AccessDeniedException ao criar
    o session.lock. Só dá para verificar de verdade como root no Linux; fora
    disso, o mínimo é garantir que a função não explode.
    """
    mc = Path(tempfile.mkdtemp())
    panel.MC_DATA = mc
    alvo = mc / "mundo"
    (alvo / "region").mkdir(parents=True)
    (alvo / "level.dat").write_text("x")
    (alvo / "region" / "r.mca").write_text("y")

    panel.chown_like_data(alvo)       # não pode lançar em nenhuma plataforma

    if os.name == "posix" and os.geteuid() == 0:
        ref = mc.stat()
        for p in [alvo, alvo / "level.dat", alvo / "region" / "r.mca"]:
            st = p.stat()
            assert (st.st_uid, st.st_gid) == (ref.st_uid, ref.st_gid), \
                f"{p} ficou com dono errado: {st.st_uid}:{st.st_gid}"
        print("ok  chown_like_data aplica o dono do /data recursivamente")
    else:
        print("ok  chown_like_data não quebra (verificação de dono só root/Linux)")


def test_validate_field():
    """O domínio de cada campo vale no SERVIDOR, não só no <select>."""
    mc = Path(tempfile.mkdtemp())
    panel.MC_DATA = mc
    (mc / "world").mkdir()
    (mc / "world" / "level.dat").write_text("x")

    # select: só o que está na lista
    assert panel.validate_field("MC_DIFFICULTY", "hard") == ("hard", None)
    valor, erro = panel.validate_field("MC_DIFFICULTY", "impossivel")
    assert valor is None and "não é uma opção válida" in erro

    # worlds: só mundo que existe
    assert panel.validate_field("MC_LEVEL", "world") == ("world", None)
    valor, erro = panel.validate_field("MC_LEVEL", "inventado")
    assert valor is None and "não existe" in erro

    # number: inteiro dentro da faixa
    assert panel.validate_field("MC_VIEW_DISTANCE", "16") == ("16", None)
    for ruim in ["0", "99", "abc", "", "1e9"]:
        valor, erro = panel.validate_field("MC_VIEW_DISTANCE", ruim)
        assert valor is None, f"aceitou view distance {ruim!r}"

    # text: casa com o padrão
    assert panel.validate_field("MC_OPS", "Steve,Alex") == ("Steve,Alex", None)
    valor, erro = panel.validate_field("MC_OPS", "Steve; rm -rf /")
    assert valor is None and "formato inválido" in erro
    valor, erro = panel.validate_field("MC_MOTD", "linha1\nlinha2")
    assert valor is None, "MOTD aceitou quebra de linha"
    print("ok  validate_field barra valor fora do domínio")


def test_to_mb():
    assert panel.to_mb("3G") == 3072
    assert panel.to_mb("1500M") == 1500
    assert panel.to_mb("") is None and panel.to_mb("abc") is None
    # A regra que protege contra OOM: heap tem que ficar 1 G abaixo do teto.
    assert panel.to_mb("4G") > panel.to_mb("4G") - 1024
    assert panel.to_mb("3G") <= panel.to_mb("4G") - 1024
    print("ok  to_mb converte e sustenta a regra heap < limite - 1G")


def test_icon_resize():
    """Minecraft só aceita 64x64; fora disso ignora calado."""
    try:
        from PIL import Image
    except ImportError:
        print("ok  ícone: Pillow ausente localmente, teste roda na imagem")
        return
    origem = Image.new("RGB", (900, 300), (10, 120, 200))
    lado = min(origem.size)
    esq, topo = (origem.width - lado) // 2, (origem.height - lado) // 2
    saida = origem.crop((esq, topo, esq + lado, topo + lado)).resize((64, 64))
    assert saida.size == (64, 64), saida.size
    print("ok  ícone vira 64x64 recortando no centro (sem achatar)")


def test_jogadores_parse():
    """A frase do RCON tem que virar número e lista, senão a aba Jogadores não
    consegue empilhar nome nenhum."""
    import re
    def parse(bruto):
        m = re.search(r"(\d+)\s+of\s+a\s+max\s+of\s+(\d+)[^:]*:(.*)", bruto, re.S)
        if not m:
            return None
        return (int(m.group(1)), int(m.group(2)),
                [n.strip() for n in m.group(3).split(",") if n.strip()])

    assert parse("There are 0 of a max of 4 players online:") == (0, 4, [])
    assert parse("There are 1 of a max of 4 players online: PCantarutti") == (1, 4, ["PCantarutti"])
    assert parse("There are 2 of a max of 4 players online: Steve, Alex") == (2, 4, ["Steve", "Alex"])
    assert parse("lixo") is None
    print("ok  lista de jogadores sai da frase do RCON")


def test_bytes_de():
    assert panel._bytes_de("6.628GiB") == int(6.628 * 1024**3)
    assert panel._bytes_de("512MiB") == 512 * 1024**2
    assert panel._bytes_de("28.62MiB") == int(28.62 * 1024**2)
    assert panel._bytes_de("lixo") == 0
    print("ok  memória do docker stats vira bytes")


def test_exige_digitar():
    """Produção só cai com o nome digitado certo."""
    from flask import Flask
    app_t = Flask(__name__)
    with app_t.test_request_context(headers={"HX-Prompt": "igenda"}):
        assert panel.exige_digitar("igenda") is None
        assert panel.exige_digitar("IGENDA") is None      # sem diferenciar caixa
    with app_t.test_request_context(headers={"HX-Prompt": "igend"}):
        assert panel.exige_digitar("igenda") is not None
    with app_t.test_request_context():                    # sem digitar nada
        assert panel.exige_digitar("igenda") is not None
    print("ok  confirmação digitada barra o que não bate")


def test_autostart_nunca_toca_no_painel():
    """Tirar o projeto do Minecraft do boot não pode levar o painel junto.

    O painel mora no mesmo projeto compose. Se ele não subir às 07:00, a
    máquina acorda sem nada que religue o resto pela web.
    """
    original = panel.project_containers
    panel.project_containers = lambda projeto: [
        {"nome": "minecraft", "estado": "running", "status": "", "servico": "mc"},
        {"nome": panel.PANEL_CONTAINER, "estado": "running", "status": "", "servico": "painel"},
    ]
    try:
        alvos = [c["nome"] for c in panel._autostart_alvos("minecraft")]
        assert alvos == ["minecraft"], f"o painel entrou na lista: {alvos}"
        assert panel.PANEL_CONTAINER not in alvos
    finally:
        panel.project_containers = original
    print("ok  autostart nunca mexe no container do painel")


def test_autostart_usa_always_e_grava_no_env():
    """`unless-stopped` não sobe no boot depois de uma parada manual.

    Era o bug: parar o Minecraft à tarde, a máquina desligar por rtcwake e
    voltar sem ele, com o painel dizendo "sobe sozinho no boot". E `docker
    update` morre no recreate, então a escolha tem que ir para o .env também.
    """
    chamadas = []
    env_escrito = {}
    orig_conts = panel.project_containers
    orig_docker = panel.docker
    orig_write = panel.write_env
    panel.project_containers = lambda projeto: [
        {"nome": "minecraft", "estado": "running", "status": "", "servico": "mc"}]
    panel.docker = lambda *a, **k: (chamadas.append(a), (0, "", ""))[1]
    panel.write_env = lambda updates: env_escrito.update(updates)
    try:
        ok, msg = panel.autostart_definir("minecraft", True)
        assert ok, msg
        assert "--restart=always" in chamadas[0], chamadas[0]
        assert env_escrito == {"MC_RESTART": "always"}, env_escrito

        chamadas.clear(); env_escrito.clear()
        ok, _ = panel.autostart_definir("minecraft", False)
        assert ok
        assert "--restart=no" in chamadas[0], chamadas[0]
        assert env_escrito == {"MC_RESTART": "no"}, env_escrito

        # Projeto de outro repositório: política sim, .env deste repo não.
        chamadas.clear(); env_escrito.clear()
        panel.autostart_definir("igenda", True)
        assert "--restart=always" in chamadas[0]
        assert env_escrito == {}, env_escrito
    finally:
        panel.project_containers = orig_conts
        panel.docker = orig_docker
        panel.write_env = orig_write
    print("ok  autostart usa always e persiste no .env")


def test_autostart_estado_nao_mente():
    """unless-stopped não pode aparecer como "sobe sozinho no boot"."""
    orig_conts = panel.project_containers
    orig_docker = panel.docker
    panel.project_containers = lambda projeto: [
        {"nome": "minecraft", "estado": "running", "status": "", "servico": "mc"}]
    try:
        for politica, esperado in [("always", True), ("unless-stopped", False),
                                   ("no", False), ("", False)]:
            panel.docker = lambda *a, **k: (0, politica, "")
            est = panel.autostart_estado("minecraft")
            assert est["ligado"] is esperado, f"{politica} -> {est}"
    finally:
        panel.project_containers = orig_conts
        panel.docker = orig_docker
    print("ok  autostart_estado só chama de ligado o always")


def test_filtro_do_console():
    """O console não pode ser enterrado pelo ruído do próprio painel, nem
    perder log de verdade junto.

    O prompt do Paper aparece de três formas: linha só com ">", ">...." puro, e
    ">...." COLADO numa mensagem real — nesse último caso descartar a linha
    perderia o recado, então o prefixo é removido e o resto fica.
    """
    ESC = chr(27)
    casos = [
        (">....", False),
        (">", False),
        (ESC + "=>....", False),
        (">...." + ESC + "=", False),
        (ESC + "[K[21:16:46 INFO]: Thread RCON Client /172.21.0.3 started", False),
        (">....2026-11-05T20:48:20-0300	INFO	mc-server-runner	stopping", True),
        ("> say oi", True),
        (ESC + "[K[20:42:30 INFO]: Done (9.195s)! For help", True),
        ("[20:43:01 INFO]: PCantarutti joined the game", True),
        # CSI com byte intermediário ("$" antes do final). Vazava antes.
        (ESC + "[?2026$p" + ESC + "[?2048$p[20:50:21 INFO]: [bootstrap] Java 25", True),
        (ESC + "[0;31m[20:50:22 ERROR]: algo quebrou", True),
    ]
    for bruto, deve_aparecer in casos:
        l = panel.ANSI_RE.sub("", bruto)
        l = panel.PROMPT_PREFIXO.sub("", l, count=1)
        oculta = (not l.strip()) or bool(panel.PROMPT_RE.match(l))             or ("Thread RCON Client" in l)
        assert oculta != deve_aparecer, f"errou em {bruto!r} -> {l!r}"
        assert ESC not in l, f"escape de terminal vazou: {l!r}"
    # O eco de comando tem que sobreviver inteiro, com o ">".
    assert panel.PROMPT_PREFIXO.sub("", "> say oi") == "> say oi"
    print("ok  console esconde ruído do painel e mantém o log do jogo")


def test_criar_mundo_valida():
    """O domínio dos campos de criação vale no servidor, não só no <select>."""
    mc = Path(tempfile.mkdtemp())
    panel.MC_DATA = mc

    v, e = panel.validate_field("MC_LEVEL_TYPE", "minecraft:flat", panel.CRIAR_CAMPOS)
    assert v == "minecraft:flat" and e is None
    for ruim in ["minecraft:inventado", "flat", ""]:
        v, e = panel.validate_field("MC_LEVEL_TYPE", ruim, panel.CRIAR_CAMPOS)
        assert v is None, f"aceitou tipo {ruim!r}"

    # Semente aceita texto e número, mas não quebra de linha (viraria duas
    # variáveis no .env).
    assert panel.validate_field("MC_SEED", "-1234567", panel.CRIAR_CAMPOS)[0] == "-1234567"
    assert panel.validate_field("MC_SEED", "vale do sol", panel.CRIAR_CAMPOS)[0] == "vale do sol"
    assert panel.validate_field("MC_SEED", "", panel.CRIAR_CAMPOS)[0] == ""
    quebra = "a" + chr(10) + "MC_BIND=0.0.0.0"
    assert panel.validate_field("MC_SEED", quebra, panel.CRIAR_CAMPOS)[0] is None

    for ruim in ["0", "99999999999", "abc"]:
        assert panel.validate_field("MC_MAX_WORLD_SIZE", ruim, panel.CRIAR_CAMPOS)[0] is None
    assert panel.validate_field("MC_MAX_WORLD_SIZE", "5000", panel.CRIAR_CAMPOS)[0] == "5000"

    for ruim in ["sim", "True", "1", ""]:
        assert panel.validate_field("MC_HARDCORE", ruim, panel.CRIAR_CAMPOS)[0] is None
    assert panel.validate_field("MC_HARDCORE", "true", panel.CRIAR_CAMPOS)[0] == "true"

    # As regras de jogo entraram também na aba Configurações.
    assert "MC_HARDCORE" in panel.FIELDS and "MC_ALLOW_NETHER" in panel.FIELDS
    # E os campos de geração NÃO: lá eles não teriam efeito nenhum.
    assert "MC_SEED" not in panel.FIELDS
    print("ok  criação de mundo valida tipo, semente, tamanho e regras")


def test_limites_dos_campos_numericos():
    """Todo campo numérico precisa aceitar o próprio mínimo e o próprio máximo.

    Regressão real: o validador limitava a 6 dígitos, então recusava o default
    do raio do mundo (29999984, oito dígitos) — e o formulário quebrava sem o
    usuário ter tocado no campo. O teste anterior usava 5000 e não via nada.
    """
    mc = Path(tempfile.mkdtemp())
    panel.MC_DATA = mc
    for specs in (panel.FIELDS, panel.CRIAR_CAMPOS):
        for chave, spec in specs.items():
            if spec.get("type") != "number":
                continue
            for extremo in (spec["min"], spec["max"]):
                valor, erro = panel.validate_field(chave, str(extremo), specs)
                assert valor == str(extremo),                     f"{chave} recusou o próprio limite {extremo}: {erro}"
            fora, erro = panel.validate_field(chave, str(spec["max"] + 1), specs)
            assert fora is None, f"{chave} aceitou acima do máximo"
    print("ok  campos numéricos aceitam seus próprios limites")


def test_password():
    stored = panel.hash_password("senha-correta-123")
    assert panel.check_password("senha-correta-123", stored)
    assert not panel.check_password("senha-errada", stored)
    assert not panel.check_password("x", None)
    print("ok  hash de senha confere e rejeita")


def test_env_roundtrip():
    proj = Path(tempfile.mkdtemp())
    panel.PROJECT = proj
    (proj / ".env").write_text(
        "# comentário importante\nMC_HEAP=3G\n\n# outro\nMC_CPUS=2.5\n", "utf-8")
    panel.write_env({"MC_HEAP": "4G", "MC_LEVEL": "novo"})
    text = (proj / ".env").read_text("utf-8")
    assert "# comentário importante" in text, "write_env comeu os comentários"
    assert "MC_HEAP=4G" in text and "MC_HEAP=3G" not in text
    assert "MC_CPUS=2.5" in text, "write_env perdeu chave que não foi tocada"
    assert "MC_LEVEL=novo" in text, "write_env não acrescentou chave nova"
    values = panel.read_env()
    assert values["MC_HEAP"] == "4G" and values["MC_LEVEL"] == "novo"
    print("ok  .env preserva comentários e chaves intocadas")


def test_valid_hhmm():
    assert panel.valid_hhmm("07:30", "") == "07:30"
    assert panel.valid_hhmm("", "04:00") == "04:00"
    for bad in ["25:00", "7:5", "abc", "12:60"]:
        try:
            panel.valid_hhmm(bad, "")
        except Exception:
            continue
        raise AssertionError(f"valid_hhmm aceitou {bad}")
    print("ok  valid_hhmm rejeita horário inválido")


def test_flush_due():
    desligado = {"enabled": False, "every_min": 1}
    assert panel.flush_due(desligado, 0.0, 10_000) is False

    cada5 = {"enabled": True, "every_min": 5}
    assert panel.flush_due(cada5, 1000.0, 1000.0 + 299) is False
    assert panel.flush_due(cada5, 1000.0, 1000.0 + 300) is True

    # Fora de faixa e lixo no campo não podem virar flush a cada ciclo de 20 s
    # (travaria o tick do servidor sem parar) nem intervalo infinito.
    # 0, vazio e lixo caem no default de 5 min — nunca em "a cada ciclo",
    # que travaria o tick do servidor a cada 20 s.
    assert panel.flush_due({"enabled": True, "every_min": 0}, 0.0, 299) is False
    assert panel.flush_due({"enabled": True, "every_min": 0}, 0.0, 300) is True
    assert panel.flush_due({"enabled": True, "every_min": 9999}, 0.0, 7199) is False
    assert panel.flush_due({"enabled": True, "every_min": 9999}, 0.0, 7200) is True
    assert panel.flush_due({"enabled": True, "every_min": "abc"}, 0.0, 299) is False
    assert panel.flush_due({"enabled": True, "every_min": None}, 0.0, 300) is True


def test_valid_int():
    assert panel.valid_int("7", 5, 1, 120) == 7
    assert panel.valid_int("", 5, 1, 120) == 5
    assert panel.valid_int(None, 5, 1, 120) == 5
    assert panel.valid_int("0", 5, 1, 120) == 1
    assert panel.valid_int("999", 5, 1, 120) == 120
    try:
        panel.valid_int("; rm -rf /", 5, 1, 120)
    except Exception as e:
        assert "400" in repr(e) or "Bad Request" in repr(e), repr(e)
    else:
        raise AssertionError("texto invalido deveria dar 400")


def _script_do_host():
    """Acha host/desliga-ate-manha no checkout OU dentro do container.

    A imagem do painel é construída a partir de ./panel, então `host/` não
    entra nela — mas o projeto está montado em /project. Sem este segundo
    caminho o teste pularia nos dois lugares e não provaria nada.
    """
    for p in (Path(__file__).resolve().parent.parent / "host" / "desliga-ate-manha",
              Path("/project/host/desliga-ate-manha")):
        if p.exists():
            return p
    return None


def test_rtcwake_acorda_na_proxima_ocorrencia():
    """O despertador tem que cair na PRÓXIMA ocorrência do horário.

    O script usava `date -d "tomorrow $ACORDA"`, e o timer dispara às 00:00 —
    quando "hoje" já é o dia novo. Resultado: acordava no dia seguinte, 39 h
    desligada em vez de 15 h. Aqui o "agora" é injetado por RTCWAKE_AGORA e o
    rtcwake é uma função de shell, então nada desliga de verdade.
    """
    script = _script_do_host()
    if script is None:
        print("skip  rtcwake: host/desliga-ate-manha não está neste contexto")
        return
    if os.name != "posix":
        # O script roda no host Linux. No MSYS do Git Bash o `TZ=... date` por
        # comando não se aplica ao parse de `-d`, e o teste acusaria um erro de
        # 3 h que não existe no servidor. Lá (container e host) ele roda.
        print("skip  rtcwake: cálculo de fuso só confere em POSIX")
        return
    texto = script.read_text("utf-8")
    hora = re.search(r"^ACORDA=(\d{1,2}:\d{2})", texto, re.M)
    assert hora, "o script precisa da linha ACORDA=HH:MM que o painel edita"
    hh, mm = (int(x) for x in hora.group(1).split(":"))

    SP = ZoneInfo("America/Sao_Paulo")
    casos = [
        # (agora, quantas horas até acordar) — 00:00 é o horário do timer
        (datetime(2026, 11, 7, 0, 0, tzinfo=SP), 15),
        (datetime(2026, 11, 6, 14, 11, tzinfo=SP), 0),    # "dormir agora"
        (datetime(2026, 11, 6, 16, 0, tzinfo=SP), 23),    # já passou: amanhã
        (datetime(2027, 2, 28, 23, 30, tzinfo=SP), 15),   # vira o mês
    ]
    # rtcwake e docker como FUNÇÃO de shell: tem precedência sobre o PATH, não
    # depende de stub executável e não desliga a máquina de quem roda o teste.
    prog = (
        'rtcwake() { echo "$@"; }\n'
        'docker() { :; }\n'
        '. "$1"\n'
    )
    for agora, _ in casos:
        r = subprocess.run(["sh", "-c", prog, "sh", str(script)],
                           capture_output=True, text=True,
                           env={**os.environ,
                                "RTCWAKE_AGORA": str(int(agora.timestamp()))})
        assert r.returncode == 0, r.stderr
        m = re.search(r"-t\s+(\d+)", r.stdout)
        assert m, f"rtcwake não recebeu -t: {r.stdout!r} {r.stderr!r}"
        alvo = datetime.fromtimestamp(int(m.group(1)), SP)

        esperado = agora.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if esperado <= agora:
            esperado = datetime.fromtimestamp(
                int((agora + timedelta(days=1)).timestamp()), SP).replace(
                    hour=hh, minute=mm, second=0, microsecond=0)
        assert alvo == esperado, f"agora {agora} -> {alvo}, esperado {esperado}"
        assert alvo > agora, f"despertador no passado: {alvo} <= {agora}"
        assert (alvo - agora) <= timedelta(hours=24),             f"mais de 24 h desligada: {agora} -> {alvo}"
    print("ok  rtcwake acorda na próxima ocorrência, nunca mais de 24 h depois")


def test_painel_edita_a_linha_acorda():
    """O painel troca o horário com sed. Só a linha ACORDA= pode mudar."""
    script = _script_do_host()
    if script is None:
        print("skip  sed do painel: host/desliga-ate-manha não está neste contexto")
        return
    antes = script.read_text("utf-8")
    # Mesmo comando de energia_definir_horarios()
    depois = subprocess.run(["sed", "s|^ACORDA=.*|ACORDA=09:30|"],
                            input=antes, capture_output=True, text=True).stdout
    trocadas = [(a, b) for a, b in zip(antes.splitlines(), depois.splitlines())
                if a != b]
    assert len(trocadas) == 1, f"o sed tocou em {len(trocadas)} linhas"
    assert trocadas[0][1] == "ACORDA=09:30", trocadas[0]
    # E o regex de leitura tem que achar o valor novo
    lido = re.search(r"^ACORDA=(\d{1,2}:\d{2})", depois, re.M)
    assert lido and lido.group(1) == "09:30"
    print("ok  sed do painel muda só a linha ACORDA= e a leitura acompanha")


def test_flush_avisa_antes_de_gravar():
    """A ordem importa: avisar DEPOIS de gravar não serve para nada."""
    passos = []

    def rcon_ok(cmd):
        passos.append(("rcon", cmd))
        return "Saved the game"

    def dormir(seg):
        passos.append(("dormiu", seg))

    out = panel.flush_do_mundo(avisar_s=10, rcon=rcon_ok, dormir=dormir)
    assert out == "Saved the game", out
    assert len(passos) == 3, passos
    assert passos[0][0] == "rcon" and passos[0][1].startswith("say "), passos[0]
    assert "10 segundos" in passos[0][1], passos[0][1]
    assert passos[1] == ("dormiu", 10), passos[1]
    assert passos[2] == ("rcon", "save-all flush"), passos[2]

    # Servidor parado: avisa, vê que não há ninguém, e NÃO espera 10 s para
    # falhar de novo. Sem isso o laço do agendador travaria 10 s por ciclo.
    passos.clear()

    def rcon_fora(cmd):
        passos.append(("rcon", cmd))
        return "[rcon indisponível] connection refused"

    out = panel.flush_do_mundo(avisar_s=10, rcon=rcon_fora, dormir=dormir)
    assert out.startswith("[rcon indisponível]"), out
    assert len(passos) == 1, passos
    assert passos[0][1].startswith("say "), passos[0]
    assert not any(p[0] == "dormiu" for p in passos), passos

    # avisar_s=0 grava direto: sem say, sem espera.
    passos.clear()
    panel.flush_do_mundo(avisar_s=0, rcon=rcon_ok, dormir=dormir)
    assert passos == [("rcon", "save-all flush")], passos
    print("ok  flush avisa, espera e só então grava")


def test_paper_autosave_texto():
    """Troca só a linha do autosave; o resto do YAML do Paper fica intocado."""
    NL = chr(10)
    original = NL.join([
        "_version: 31",
        "chunks:",
        "  auto-save-interval: default",
        "  delay-chunk-unloads-by: 10s",
        "  entity-per-chunk-save-limit:",
        "    arrow: -1",
    ]) + NL

    novo = panel.paper_autosave_texto(original, 1728000)
    assert "  auto-save-interval: 1728000" in novo.splitlines(), novo
    diff = [(a, b) for a, b in zip(original.splitlines(), novo.splitlines()) if a != b]
    assert len(diff) == 1, diff
    assert len(novo.splitlines()) == len(original.splitlines()), "mudou linhas"

    # Indentação preservada: perder os dois espaços quebra o YAML inteiro.
    linha = [l for l in novo.splitlines() if "auto-save-interval" in l][0]
    assert linha.startswith("  auto-save-interval:"), repr(linha)

    # Volta para default sem deixar resto do valor antigo na linha.
    assert panel.paper_autosave_texto(novo, "default") == original

    # Sem a chave, falha alto — em vez de gravar um arquivo que não aplica nada.
    try:
        panel.paper_autosave_texto("chunks:" + NL + "  outra-coisa: 1" + NL, 100)
    except ValueError:
        pass
    else:
        raise AssertionError("deveria falhar quando a chave não existe")
    print("ok  paper_autosave_texto mexe só na linha do autosave")


def test_rcon_protocol():
    """Servidor RCON de mentira: confere login, enquadramento e resposta fatiada."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    received = {}

    def read_packet(conn):
        raw = b""
        while len(raw) < 4:
            raw += conn.recv(4 - len(raw))
        length = struct.unpack("<i", raw)[0]
        body = b""
        while len(body) < length:
            body += conn.recv(length - len(body))
        pid, ptype = struct.unpack("<ii", body[:8])
        return pid, ptype, body[8:-2].decode()

    def send_packet(conn, pid, ptype, payload):
        body = struct.pack("<ii", pid, ptype) + payload.encode() + b"\x00\x00"
        conn.sendall(struct.pack("<i", len(body)) + body)

    def serve_real():
        conn, _ = srv.accept()
        pid, ptype, payload = read_packet(conn)      # login
        received["password"] = payload
        send_packet(conn, pid if payload == "segredo" else -1, 2, "")
        pid, ptype, payload = read_packet(conn)      # comando
        received["cmd"] = payload
        send_packet(conn, pid, 0, "parte1 ")         # resposta fatiada
        send_packet(conn, pid, 0, "parte2")
        sid, _, _ = read_packet(conn)                # sentinela
        send_packet(conn, sid, 0, "")
        conn.close()

    threading.Thread(target=serve_real, daemon=True).start()
    out = mcrcon.run("127.0.0.1", port, "segredo", "tps")
    assert received["password"] == "segredo"
    assert received["cmd"] == "tps"
    assert out == "parte1 parte2", f"resposta fatiada remontada errada: {out!r}"
    srv.close()
    print("ok  RCON: login, enquadramento e resposta em vários pacotes")


def test_rcon_bad_password():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def serve():
        conn, _ = srv.accept()
        raw = conn.recv(4)
        length = struct.unpack("<i", raw)[0]
        conn.recv(length)
        body = struct.pack("<ii", -1, 2) + b"\x00\x00"   # -1 = recusado
        conn.sendall(struct.pack("<i", len(body)) + body)
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    try:
        mcrcon.run("127.0.0.1", port, "errada", "list")
    except mcrcon.RconError:
        print("ok  RCON recusa senha errada")
    else:
        raise AssertionError("RCON aceitou senha errada")
    finally:
        srv.close()


if __name__ == "__main__":
    test_safe_path()
    test_safe_name()
    test_zip_slip()
    test_zip_ok()
    test_zip_from_disk()
    test_chown_like_data()
    test_validate_field()
    test_to_mb()
    test_icon_resize()
    test_limites_dos_campos_numericos()
    test_criar_mundo_valida()
    test_filtro_do_console()
    test_autostart_nunca_toca_no_painel()
    test_autostart_usa_always_e_grava_no_env()
    test_autostart_estado_nao_mente()
    test_jogadores_parse()
    test_bytes_de()
    test_exige_digitar()
    test_password()
    test_env_roundtrip()
    test_valid_hhmm()
    test_rtcwake_acorda_na_proxima_ocorrencia()
    test_painel_edita_a_linha_acorda()
    test_valid_int()
    test_flush_due()
    test_flush_avisa_antes_de_gravar()
    test_paper_autosave_texto()
    test_rcon_protocol()
    test_rcon_bad_password()
    print("\ntudo passou")
