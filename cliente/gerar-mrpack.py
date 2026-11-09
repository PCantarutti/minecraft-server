"""Gera o modpack (.mrpack) que os jogadores importam no Modrinth App / Prism.

Só o necessário para ouvir a música: Fabric + Fabric API + Simple Voice Chat,
nas versões mais novas para a versão do Minecraft dada. Grava também
`mods.json`, que a página /mods do painel lê para mostrar os links individuais
(para quem quer instalar numa instância que já tem).

    python cliente/gerar-mrpack.py 26.3
"""
import json
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

UA = {"User-Agent": "servidor-minecraft/gerar-mrpack"}
MODS = ["fabric-api", "simple-voice-chat"]


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA)) as r:
        return json.load(r)


def main(mc):
    loader = next(l["loader"]["version"] for l in get(f"https://meta.fabricmc.net/v2/versions/loader/{mc}") if l["loader"]["stable"])
    files, mods = [], []
    for slug in MODS:
        versions = get(f"https://api.modrinth.com/v2/project/{slug}/version?" + urllib.parse.urlencode({"game_versions": f'["{mc}"]', "loaders": '["fabric"]'}))
        if not versions:
            sys.exit(f"{slug} não tem versão Fabric para {mc}")
        f = next(x for x in versions[0]["files"] if x["primary"])  # mais nova, beta inclusa (igual ao servidor)
        files.append({
            "path": f"mods/{f['filename']}",
            "hashes": {"sha1": f["hashes"]["sha1"], "sha512": f["hashes"]["sha512"]},
            "env": {"client": "required", "server": "unsupported"},
            "downloads": [f["url"]],
            "fileSize": f["size"],
        })
        mods.append({
            "nome": get(f"https://api.modrinth.com/v2/project/{slug}")["title"],
            "versao": versions[0]["version_number"],
            "url": f"https://modrinth.com/mod/{slug}/versions?g={mc}&l=fabric",
        })
        print(f"  {slug}: {versions[0]['version_number']}")
    index = {
        "formatVersion": 1, "game": "minecraft", "versionId": mc,
        "name": f"Servidor do Pedro {mc}",
        "summary": "Fabric + Simple Voice Chat para ouvir a música do servidor",
        "files": files,
        "dependencies": {"minecraft": mc, "fabric-loader": loader},
    }
    out = Path(__file__).with_name(f"servidor-do-pedro-{mc}.mrpack")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("modrinth.index.json", json.dumps(index, indent=2))
    (out.parent / "mods.json").write_text(json.dumps(
        {"minecraft": mc, "loader": "Fabric", "modpack": out.name, "mods": mods}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"fabric-loader {loader} -> {out} + mods.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "26.3")
