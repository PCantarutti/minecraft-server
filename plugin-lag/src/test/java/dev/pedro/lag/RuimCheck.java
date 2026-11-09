package dev.pedro.lag;

import java.util.ArrayDeque;
import java.util.List;

/** Self-check da regra de "conexão ruim": `./gradlew check` roda isto. */
public final class RuimCheck {
    static boolean r(List<Integer> pings) { return Conexao.ruim(new ArrayDeque<>(pings), 300, 250); }

    public static void main(String[] a) {
        if (r(List.of())) throw new AssertionError("vazio não é ruim");
        if (r(List.of(80, 90, 100))) throw new AssertionError("ping bom estável");
        if (!r(List.of(80, 90, 320))) throw new AssertionError("ping atual alto");
        if (!r(List.of(40, 300, 60))) throw new AssertionError("oscilação 260 pega mesmo com ping atual bom");
        if (r(List.of(50, 290, 60))) throw new AssertionError("oscilação 240 fica abaixo de 250");
        if (Conexao.ruim(new ArrayDeque<>(List.of(40, 600, 60)), 300, 0)) throw new AssertionError("oscilação 0 = desligada");
        System.out.println("ok  regra de conexão ruim");
    }
}
