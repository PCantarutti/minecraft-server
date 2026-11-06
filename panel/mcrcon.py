"""Cliente RCON do Minecraft, só com a stdlib.

O protocolo é pequeno o bastante para não justificar dependência: pacote de
tamanho + id + tipo + payload ASCII terminado em dois NULs.

Spec: https://wiki.vg/RCON
"""

import socket
import struct

TYPE_LOGIN = 3
TYPE_COMMAND = 2
TYPE_RESPONSE = 0

# O servidor responde id=-1 quando a senha está errada. Qualquer outro id é
# eco do que mandamos, e é assim que casamos resposta com requisição.
AUTH_FAIL_ID = -1


class RconError(Exception):
    pass


class Rcon:
    def __init__(self, host, port, password, timeout=10):
        self.host = host
        self.port = int(port)
        self.password = password
        self.timeout = timeout
        self.sock = None
        self._id = 0

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock.settimeout(self.timeout)
        req_id = self._send(TYPE_LOGIN, self.password)
        resp_id, _ = self._recv()
        if resp_id == AUTH_FAIL_ID or resp_id != req_id:
            self.close()
            raise RconError("senha do RCON recusada")

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def command(self, cmd):
        if not self.sock:
            raise RconError("não conectado")
        req_id = self._send(TYPE_COMMAND, cmd)
        # Respostas longas (ex.: `help`) vêm fatiadas em vários pacotes. O truque
        # padrão é mandar um pacote vazio depois e ler até a resposta dele voltar:
        # o servidor processa em ordem, então o eco do vazio marca o fim.
        sentinel_id = self._send(TYPE_RESPONSE, "")
        chunks = []
        while True:
            resp_id, body = self._recv()
            if resp_id == sentinel_id:
                break
            if resp_id == req_id:
                chunks.append(body)
        return "".join(chunks).strip()

    # -- protocolo ---------------------------------------------------------
    def _send(self, packet_type, payload):
        self._id += 1
        body = struct.pack("<ii", self._id, packet_type) + payload.encode("utf-8") + b"\x00\x00"
        self.sock.sendall(struct.pack("<i", len(body)) + body)
        return self._id

    def _recv(self):
        length = struct.unpack("<i", self._read_exactly(4))[0]
        if length < 10 or length > 4096 * 16:
            raise RconError(f"tamanho de pacote implausível: {length}")
        data = self._read_exactly(length)
        resp_id, _type = struct.unpack("<ii", data[:8])
        return resp_id, data[8:-2].decode("utf-8", errors="replace")

    def _read_exactly(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise RconError("conexão fechada pelo servidor")
            buf += chunk
        return buf


def run(host, port, password, cmd, timeout=10):
    """Conecta, roda um comando, desconecta. Uso pontual."""
    with Rcon(host, port, password, timeout) as r:
        return r.command(cmd)
