package dev.pedro.lag;

import java.util.Collection;

/** Regra pura (sem Bukkit) para o self-check rodar sem servidor. */
final class Conexao {
    private Conexao() {}

    /**
     * Ruim = ping atual alto, ou oscilando demais na janela (sintoma de perda
     * de pacote). `h` em ordem de chegada; o último é o atual.
     */
    static boolean ruim(Collection<Integer> h, int pingAlto, int oscilacao) {
        if (h.isEmpty()) return false;
        int min = Integer.MAX_VALUE, max = 0, atual = 0;
        for (int v : h) { min = Math.min(min, v); max = Math.max(max, v); atual = v; }
        if (atual >= pingAlto) return true;
        return oscilacao > 0 && h.size() >= 2 && max - min >= oscilacao;
    }
}
