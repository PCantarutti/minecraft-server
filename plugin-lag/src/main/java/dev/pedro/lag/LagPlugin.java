package dev.pedro.lag;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.format.NamedTextColor;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.PlayerDeathEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.plugin.java.JavaPlugin;

/**
 * Quem morre com a conexão ruim mantém inventário e XP — só essa pessoa.
 *
 * Por player, e não pela gamerule: a gamerule vale para o servidor inteiro, e
 * um jogador com lag não deveria dar keepInventory para todo mundo.
 */
public final class LagPlugin extends JavaPlugin implements Listener {

    private final Map<UUID, Deque<Integer>> pings = new HashMap<>();
    /** Até quando (System.currentTimeMillis) cada um está protegido. */
    private final Map<UUID, Long> protegidoAte = new HashMap<>();

    private int pingAlto, oscilacao, janela;
    private long extraMs;
    private boolean avisar;

    @Override
    public void onEnable() {
        saveDefaultConfig();
        var c = getConfig();
        pingAlto = c.getInt("ping-alto-ms", 300);
        oscilacao = c.getInt("oscilacao-ms", 250);
        janela = Math.max(2, c.getInt("janela-s", 20));
        extraMs = c.getLong("protecao-extra-s", 30) * 1000;
        avisar = c.getBoolean("avisar", true);
        getServer().getPluginManager().registerEvents(this, this);
        getServer().getScheduler().runTaskTimer(this, this::amostrar, 20, 20);
    }

    /** 1x por segundo: guarda o ping de cada um e marca quem está ruim. */
    private void amostrar() {
        long agora = System.currentTimeMillis();
        for (Player p : getServer().getOnlinePlayers()) {
            int ping = p.getPing();
            if (ping <= 0) continue; // recém-entrado: ainda sem medida
            Deque<Integer> h = pings.computeIfAbsent(p.getUniqueId(), k -> new ArrayDeque<>());
            h.addLast(ping);
            while (h.size() > janela) h.removeFirst();
            if (Conexao.ruim(h, pingAlto, oscilacao)) {
                if (!protegidoAte.containsKey(p.getUniqueId()) || agora > protegidoAte.get(p.getUniqueId())) {
                    getLogger().info(p.getName() + " com conexão ruim (ping " + ping + " ms): protegido");
                }
                protegidoAte.put(p.getUniqueId(), agora + extraMs);
            }
        }
    }

    // HIGH: roda depois de plugins que mexem nos drops e vê o keepInventory final.
    @EventHandler(priority = EventPriority.HIGH, ignoreCancelled = true)
    public void aoMorrer(PlayerDeathEvent e) {
        if (e.getKeepInventory()) return; // gamerule (ou outro plugin) já cobriu
        Long ate = protegidoAte.get(e.getPlayer().getUniqueId());
        if (ate == null || System.currentTimeMillis() > ate) return;
        e.setKeepInventory(true);
        e.getDrops().clear(); // sem isso o item fica no inventário E no chão
        e.setKeepLevel(true);
        e.setDroppedExp(0);
        getLogger().info(e.getPlayer().getName() + " morreu com lag: manteve os itens");
        if (avisar) {
            e.getPlayer().sendMessage(Component.text(
                "Sua conexão estava ruim quando você morreu — itens e XP mantidos.",
                NamedTextColor.YELLOW));
        }
    }

    @EventHandler
    public void aoSair(PlayerQuitEvent e) {
        pings.remove(e.getPlayer().getUniqueId());
        protegidoAte.remove(e.getPlayer().getUniqueId());
    }
}
