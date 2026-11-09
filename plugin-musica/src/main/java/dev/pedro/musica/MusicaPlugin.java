package dev.pedro.musica;

import de.maxhenkel.voicechat.api.BukkitVoicechatService;
import de.maxhenkel.voicechat.api.VoicechatApi;
import de.maxhenkel.voicechat.api.VoicechatPlugin;
import de.maxhenkel.voicechat.api.VoicechatServerApi;
import de.maxhenkel.voicechat.api.audiochannel.StaticAudioChannel;
import de.maxhenkel.voicechat.api.events.EventRegistration;
import de.maxhenkel.voicechat.api.events.PlayerConnectedEvent;
import de.maxhenkel.voicechat.api.events.PlayerDisconnectedEvent;
import de.maxhenkel.voicechat.api.events.VoicechatServerStartedEvent;
import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.event.ClickEvent;
import net.kyori.adventure.text.format.NamedTextColor;
import net.kyori.adventure.text.format.TextDecoration;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.command.TabExecutor;
import org.bukkit.plugin.java.JavaPlugin;

import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

public final class MusicaPlugin extends JavaPlugin implements VoicechatPlugin, TabExecutor, Listener {
    static final String CATEGORY = "musica";

    /** Um canal estático por jogador conectado ao voice chat: todos ouvem igual, sem posição. */
    final Map<UUID, StaticAudioChannel> channels = new ConcurrentHashMap<>();
    volatile VoicechatServerApi voice;
    Music music;
    Telas telas;
    Biblioteca biblioteca;

    @Override
    public void onEnable() {
        saveDefaultConfig();
        music = new Music(this);
        telas = new Telas(this);
        biblioteca = new Biblioteca(getDataFolder().toPath().resolve("biblioteca.json"));
        getCommand("music").setExecutor(this);
        BukkitVoicechatService svc = getServer().getServicesManager().load(BukkitVoicechatService.class);
        if (svc == null) throw new IllegalStateException("Simple Voice Chat não encontrado");
        svc.registerPlugin(this);
        getServer().getPluginManager().registerEvents(this, this);
        getServer().getScheduler().runTaskTimer(this, music::updateBar, 20, 20);
        if (getConfig().getBoolean("ytdlp.update-on-start", true)) music.updateYtDlp();
    }

    /** Quem entrou sem o Simple Voice Chat recebe o link para instalar (servidor não consegue instalar mod no cliente). */
    @EventHandler
    public void onJoin(PlayerJoinEvent e) {
        Player p = e.getPlayer();
        getServer().getScheduler().runTaskLater(this, () -> {
            if (!p.isOnline() || voice == null) return;
            var conn = voice.getConnectionOf(p.getUniqueId());
            if (conn != null && conn.isInstalled()) return;
            // Página /mods do painel (modpack + links), vinda do compose; sem ela, a página do mod no Modrinth.
            String page = System.getenv().getOrDefault("MUSICA_MODS_URL", getConfig().getString("mods-page-url", ""));
            String url = page.isBlank()
                    ? "https://modrinth.com/mod/simple-voice-chat/versions?g=" + getServer().getMinecraftVersion()
                    : page;
            p.sendMessage(Component.text("♪ Para ouvir a música do servidor, instale o ", NamedTextColor.GOLD)
                    .append(Component.text("Simple Voice Chat", NamedTextColor.AQUA, TextDecoration.UNDERLINED)
                            .clickEvent(ClickEvent.openUrl(url))
                            .hoverEvent(Component.text(url)))
                    .append(Component.text(". Clique no nome para ver como.", NamedTextColor.GOLD)));

        }, 20 * 10); // 10 s: tempo do voice chat do cliente se conectar
    }

    /** Botões da tela "♪ Música" do datapack (ações custom "musica:<id>", sem comando). */
    @EventHandler
    public void onCustomClick(io.papermc.paper.event.player.PlayerCustomClickEvent e) {
        if (e.getIdentifier().namespace().equals("musica")
                && e.getCommonConnection() instanceof io.papermc.paper.connection.PlayerGameConnection c)
            telas.custom(c.getPlayer(), e.getIdentifier().value(), e.getDialogResponseView());
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent e) { telas.forget(e.getPlayer()); }

    @Override
    public void onDisable() {
        if (music != null) music.shutdown();
    }

    // --- Simple Voice Chat ---

    @Override public String getPluginId() { return "musica"; }

    @Override public void initialize(VoicechatApi api) {}

    @Override
    public void registerEvents(EventRegistration reg) {
        reg.registerEvent(VoicechatServerStartedEvent.class, e -> {
            voice = e.getVoicechat();
            // Aparece no menu do voice chat: cada jogador ajusta/muta a música no próprio cliente.
            voice.registerVolumeCategory(voice.volumeCategoryBuilder()
                    .setId(CATEGORY).setName("Música").setDescription("Música do servidor").build());
        });
        reg.registerEvent(PlayerConnectedEvent.class, e -> {
            var conn = e.getConnection();
            var ch = voice.createStaticAudioChannel(UUID.randomUUID(), conn.getPlayer().getServerLevel(), conn);
            if (ch == null) return;
            ch.setCategory(CATEGORY);
            channels.put(conn.getPlayer().getUuid(), ch);
        });
        reg.registerEvent(PlayerDisconnectedEvent.class, e -> channels.remove(e.getPlayerUuid()));
    }

    // --- /music ---

    @Override
    public boolean onCommand(CommandSender s, Command c, String label, String[] a) {
        if (a.length == 0) { // /music sozinho abre o player
            if (s instanceof Player p) { telas.player(p); return true; }
            return false;
        }
        String rest = String.join(" ", List.of(a).subList(1, a.length)).trim();
        switch (a[0].toLowerCase()) {
            case "play", "playlist" -> {
                if (rest.isEmpty()) return false;
                music.enqueue(s, rest, a[0].equalsIgnoreCase("playlist"));
            }
            // Botões da tela de controle (datapack): cada ação termina abrindo outra tela, sem fechar o menu.
            case "tela" -> {
                if (s instanceof Player p) telas.control(p, rest);
            }
            case "queue", "fila" -> {
                if (s instanceof Player p) telas.queue(p); else music.showQueue(s);
            }
            case "skip" -> music.skip(s);
            case "shuffle" -> music.shuffle(s);
            case "pause" -> music.pause(s); // alterna pausar/continuar
            case "next" -> { // /music next <n>: a n-ésima da fila toca a seguir
                var items = music.queued();
                try {
                    music.moveNext(s, items.get(Integer.parseInt(rest) - 1));
                } catch (NumberFormatException | IndexOutOfBoundsException ex) {
                    s.sendMessage("§cUso: /music next <posição na fila, 1-" + items.size() + ">");
                }
            }
            case "stop" -> music.stop(s);
            case "volume" -> {
                try {
                    music.volume(s, (int) Double.parseDouble(rest)); // a tela de controle manda "50.0"
                } catch (NumberFormatException ex) {
                    s.sendMessage("§cUso: /music volume <0-100>");
                }
            }
            default -> { return false; }
        }
        return true;
    }

    @Override
    public List<String> onTabComplete(CommandSender s, Command c, String label, String[] a) {
        if (a.length != 1) return List.of();
        return List.of("play", "playlist", "queue", "next", "shuffle", "pause", "skip", "stop", "volume").stream()
                .filter(x -> x.startsWith(a[0].toLowerCase())).toList();
    }
}
