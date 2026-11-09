package dev.pedro.musica;

import com.sedmelluq.discord.lavaplayer.format.Pcm16AudioDataFormat;
import com.sedmelluq.discord.lavaplayer.player.AudioLoadResultHandler;
import com.sedmelluq.discord.lavaplayer.player.AudioPlayer;
import com.sedmelluq.discord.lavaplayer.player.AudioPlayerManager;
import com.sedmelluq.discord.lavaplayer.player.DefaultAudioPlayerManager;
import com.sedmelluq.discord.lavaplayer.player.event.AudioEventAdapter;
import com.sedmelluq.discord.lavaplayer.source.AudioSourceManagers;
import com.sedmelluq.discord.lavaplayer.tools.FriendlyException;
import com.sedmelluq.discord.lavaplayer.track.AudioPlaylist;
import com.sedmelluq.discord.lavaplayer.track.AudioTrack;
import com.sedmelluq.discord.lavaplayer.track.AudioTrackEndReason;
import de.maxhenkel.voicechat.api.opus.OpusEncoder;
import net.kyori.adventure.bossbar.BossBar;
import net.kyori.adventure.text.Component;
import org.bukkit.Bukkit;
import org.bukkit.command.CommandSender;

import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.BlockingDeque;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executors;
import java.util.concurrent.LinkedBlockingDeque;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.logging.Level;

final class Music extends AudioEventAdapter {
    /**
     * Item da fila: faixa já carregada pelo lavaplayer (SoundCloud, link direto), ou {@code query} do
     * yt-dlp (link/busca do YouTube) que só é resolvida na hora de tocar, porque a URL do áudio expira.
     */
    record Entry(String title, AudioTrack track, String query) {
        private static final java.util.regex.Pattern YT_ID = java.util.regex.Pattern.compile("(?:v=|youtu\\.be/|shorts/)([\\w-]{11})");

        /** Capa: artwork do lavaplayer, ou a miniatura do YouTube quando o link tem o id do vídeo. */
        String thumbUrl() {
            if (track != null) return track.getInfo().artworkUrl;
            var m = YT_ID.matcher(query);
            return m.find() ? Thumb.youtube(m.group(1)) : null;
        }
    }

    private final MusicaPlugin plugin;
    private final AudioPlayerManager manager = new DefaultAudioPlayerManager();
    private final AudioPlayer player;
    private final BlockingDeque<Entry> queue = new LinkedBlockingDeque<>();
    private final ScheduledExecutorService ticker = Executors.newSingleThreadScheduledExecutor(r -> new Thread(r, "musica-audio"));
    private final Spotify spotify;
    private final YtDlp ytdlp;
    private final Path cache;
    private OpusEncoder encoder;
    private volatile boolean loading; // resolvendo a próxima faixa no yt-dlp
    private volatile String nowThumb;
    private volatile String nowUrl; // para salvar a faixa atual numa playlist
    /** "Tocando agora" no topo da tela de todos (servidor não desenha em canto livre; isso exigiria mod no cliente). */
    private final BossBar bar = BossBar.bossBar(Component.empty(), 0f, BossBar.Color.PINK, BossBar.Overlay.PROGRESS);

    Music(MusicaPlugin plugin) {
        this.plugin = plugin;
        var cfg = plugin.getConfig();
        this.spotify = new Spotify(cfg.getString("spotify.client-id", ""), cfg.getString("spotify.client-secret", ""));
        this.ytdlp = new YtDlp(cfg.getStringList("ytdlp.command"));
        // Mono 48 kHz, 20 ms (960 amostras): exatamente o quadro que o encoder do voice chat espera.
        manager.getConfiguration().setOutputFormat(new Pcm16AudioDataFormat(1, 48000, 960, true));
        // YouTube fica com o yt-dlp; o extrator interno do lavaplayer está quebrado.
        AudioSourceManagers.registerRemoteSources(manager,
                com.sedmelluq.discord.lavaplayer.source.youtube.YoutubeAudioSourceManager.class);
        AudioSourceManagers.registerLocalSource(manager); // arquivos baixados pelo yt-dlp
        cache = plugin.getDataFolder().toPath().resolve("cache").toAbsolutePath();
        try { // sobras de um desligamento no meio da música
            if (Files.isDirectory(cache)) try (var old = Files.list(cache)) { for (var f : old.toList()) Files.deleteIfExists(f); }
            Files.createDirectories(cache);
        } catch (Exception e) {
            throw new IllegalStateException("não consegui preparar " + cache, e);
        }
        player = manager.createPlayer();
        player.setVolume(50);
        player.addListener(this);
        ticker.scheduleAtFixedRate(this::tick, 0, 20, TimeUnit.MILLISECONDS);
    }

    /** A cada 20 ms: um quadro PCM -> codifica uma vez -> manda o mesmo pacote Opus a todos. */
    private void tick() {
        try {
            var voice = plugin.voice;
            if (voice == null) return;
            var frame = player.provide();
            if (frame == null) return; // nada tocando ou buffer vazio: não manda nada
            if (encoder == null) encoder = voice.createEncoder();
            var sb = ByteBuffer.wrap(frame.getData()).asShortBuffer();
            short[] pcm = new short[sb.remaining()];
            sb.get(pcm);
            byte[] opus = encoder.encode(pcm);
            for (var it = plugin.channels.values().iterator(); it.hasNext(); ) {
                var ch = it.next();
                if (ch.isClosed()) it.remove(); else ch.send(opus);
            }
        } catch (Throwable t) {
            plugin.getLogger().log(Level.WARNING, "Erro no envio de áudio", t);
        }
    }

    void enqueue(CommandSender s, String input, boolean playlist) {
        boolean url = input.startsWith("http://") || input.startsWith("https://");
        if (url && input.contains("spotify.com/")) {
            async(s, () -> {
                List<String> names = spotify.trackNames(input);
                names.forEach(n -> queue.add(new Entry(n, null, "ytsearch1:" + n)));
                s.sendMessage("§aSpotify: " + names.size() + " faixa(s) na fila.");
                startIfIdle();
            });
        } else if (!url || YtDlp.isYoutube(input)) {
            if (playlist) {
                async(s, () -> {
                    var items = ytdlp.playlist(input);
                    items.forEach(e -> queue.add(new Entry(e[0], null, e[1])));
                    s.sendMessage("§aPlaylist: " + items.size() + " faixa(s) na fila.");
                    startIfIdle();
                });
            } else {
                queue.add(new Entry(input, null, url ? input : "ytsearch1:" + input));
                s.sendMessage("§aNa fila: " + input);
                startIfIdle();
            }
        } else {
            loadLavaplayer(s, input);
        }
    }

    /** SoundCloud, links diretos de áudio etc. */
    private void loadLavaplayer(CommandSender s, String url) {
        manager.loadItem(url, new AudioLoadResultHandler() {
            @Override public void trackLoaded(AudioTrack t) {
                queue.add(new Entry(t.getInfo().title, t, null));
                s.sendMessage("§aNa fila: " + t.getInfo().title);
                startIfIdle();
            }

            @Override public void playlistLoaded(AudioPlaylist p) {
                p.getTracks().forEach(t -> queue.add(new Entry(t.getInfo().title, t, null)));
                s.sendMessage("§aPlaylist " + p.getName() + ": " + p.getTracks().size() + " faixa(s) na fila.");
                startIfIdle();
            }

            @Override public void noMatches() { s.sendMessage("§cNada encontrado: " + url); }

            @Override public void loadFailed(FriendlyException e) { s.sendMessage("§cFalhou: " + e.getMessage()); }
        });
    }

    private synchronized void startIfIdle() {
        if (player.getPlayingTrack() == null && !loading) next();
    }

    private synchronized void next() {
        Entry e = queue.poll();
        if (e == null) { player.stopTrack(); plugin.telas.refreshOpen(); return; }
        nowThumb = e.thumbUrl();
        nowUrl = e.track() != null ? e.track().getInfo().uri : e.query();
        if (e.track() != null) { play(e.track(), e.title()); return; }
        loading = true;
        Thread.ofVirtual().start(() -> {
            try {
                // ponytail: baixa só na vez da faixa (~5 s de silêncio entre músicas); pré-baixar a próxima se incomodar
                String[] r = ytdlp.download(e.query(), cache); // {título, arquivo}
                AudioTrack t = loadDirect(r[1]);
                String id = Path.of(r[1]).getFileName().toString().replaceFirst("\\.[^.]+$", ""); // arquivo = <id>.<ext>
                if (id.length() == 11) { nowThumb = Thumb.youtube(id); nowUrl = "https://www.youtube.com/watch?v=" + id; }
                synchronized (this) { loading = false; play(t, r[0]); }
            } catch (Exception ex) {
                Bukkit.broadcastMessage("§cNão deu para tocar " + e.title() + ": " + ex.getMessage());
                synchronized (this) { loading = false; next(); }
            }
        });
    }

    private AudioTrack loadDirect(String url) throws Exception {
        var f = new CompletableFuture<AudioTrack>();
        manager.loadItem(url, new AudioLoadResultHandler() {
            @Override public void trackLoaded(AudioTrack t) { f.complete(t); }
            @Override public void playlistLoaded(AudioPlaylist p) { f.completeExceptionally(new IllegalStateException("playlist inesperada")); }
            @Override public void noMatches() { f.completeExceptionally(new IllegalStateException("formato não suportado")); }
            @Override public void loadFailed(FriendlyException e) { f.completeExceptionally(e); }
        });
        return f.get(30, TimeUnit.SECONDS);
    }

    private void play(AudioTrack t, String title) {
        t.setUserData(title);
        player.setPaused(false); // pular/parar com a música pausada não deixa a próxima muda
        player.startTrack(t, false);
        Bukkit.broadcastMessage("§d♪ Tocando: §f" + title);
        plugin.telas.refreshOpen();
    }

    @Override
    public void onTrackEnd(AudioPlayer p, AudioTrack t, AudioTrackEndReason reason) {
        deleteIfCached(t);
        if (reason.mayStartNext && !loading) next(); // se já está baixando a próxima, ela começa sozinha
    }

    @Override
    public void onTrackException(AudioPlayer p, AudioTrack t, FriendlyException e) {
        plugin.getLogger().warning("Erro tocando " + t.getUserData() + ": " + e.getMessage());
    }

    private void deleteIfCached(AudioTrack t) {
        try {
            var f = Path.of(t.getIdentifier());
            if (f.startsWith(cache)) Files.deleteIfExists(f);
        } catch (Exception ignored) {} // identificador não é caminho (SoundCloud, URL)
    }

    /** Thread principal, 1x/s: título + tempo, barra enchendo com o progresso. */
    void updateBar() {
        var t = player.getPlayingTrack();
        var online = Bukkit.getOnlinePlayers();
        if (t == null && !loading) { online.forEach(p -> p.hideBossBar(bar)); return; }
        if (t == null) {
            bar.name(Component.text("♪ Carregando...")).progress(0f);
        } else {
            long dur = t.getDuration(), pos = t.getPosition();
            boolean live = t.getInfo().isStream || dur <= 0;
            bar.name(Component.text((player.isPaused() ? "⏸ " : "♪ ") + t.getUserData() + (live ? "" : "   " + clock(pos) + " / " + clock(dur))))
                    .progress(live ? 1f : Math.clamp((float) pos / dur, 0f, 1f));
        }
        online.forEach(p -> p.showBossBar(bar)); // idempotente; pega quem entrou depois
    }

    static String clock(long ms) {
        long s = ms / 1000;
        return s / 60 + ":" + String.format("%02d", s % 60);
    }

    // --- leitura para a tela de controle ---
    List<Entry> queued() { return new ArrayList<>(queue); }
    AudioTrack playing() { return player.getPlayingTrack(); }
    boolean isLoading() { return loading; }
    String nowThumb() { return nowThumb; }
    String nowUrl() { return nowUrl; }
    String nextTitle() { var e = queue.peek(); return e == null ? null : e.title(); }
    int volume() { return player.getVolume(); }
    YtDlp ytdlp() { return ytdlp; }

    /** Faixa escolhida na lista de resultados. */
    void add(CommandSender s, String title, String url, boolean first) {
        var e = new Entry(title, null, url);
        if (first) queue.addFirst(e); else queue.add(e);
        s.sendMessage((first ? "§aToca a seguir: " : "§aNa fila: ") + title);
        startIfIdle();
    }

    /** Playlist salva: entra no fim da fila (embaralhada se pedido). */
    void addAll(CommandSender s, List<Biblioteca.Faixa> faixas, boolean shuffled, boolean first) {
        var l = new ArrayList<>(faixas);
        if (shuffled) java.util.Collections.shuffle(l);
        if (first) java.util.Collections.reverse(l); // addFirst inverte: ao contrário para sair na ordem
        l.forEach(f -> { var e = new Entry(f.title(), null, f.url()); if (first) queue.addFirst(e); else queue.add(e); });
        Bukkit.broadcastMessage("§a" + s.getName() + " pôs " + l.size() + " faixa(s) na fila.");
        startIfIdle();
    }

    /** Toca já: entra na frente da fila e substitui a atual (que segue tocando até a nova baixar). */
    synchronized void playNow(CommandSender s, String title, String url) {
        queue.addFirst(new Entry(title, null, url));
        Bukkit.broadcastMessage("§e" + s.getName() + " tocou agora: §f" + title);
        if (!loading) next(); // ponytail: se outra já estiver baixando, ela toca primeiro e esta logo depois
    }

    /** Passa a faixa para a frente da fila (some se já tiver começado a tocar). */
    synchronized void moveNext(CommandSender s, Entry e) {
        if (!queue.remove(e)) return;
        queue.addFirst(e);
        Bukkit.broadcastMessage("§e" + s.getName() + " pôs a seguir: §f" + e.title());
    }

    /** drainTo em vez de clear: o que entrar na fila durante o embaralho não se perde. */
    synchronized void shuffle(CommandSender s) {
        List<Entry> items = new ArrayList<>();
        queue.drainTo(items);
        java.util.Collections.shuffle(items);
        queue.addAll(items);
        Bukkit.broadcastMessage("§e" + s.getName() + " aleatorizou a fila (" + items.size() + " faixas).");
    }

    void showQueue(CommandSender s) {
        var now = player.getPlayingTrack();
        s.sendMessage("§dTocando: §f" + (now == null ? (loading ? "carregando..." : "nada") : now.getUserData()));
        List<Entry> items = new ArrayList<>(queue);
        for (int i = 0; i < Math.min(10, items.size()); i++) s.sendMessage("§7" + (i + 1) + ". §f" + items.get(i).title());
        if (items.size() > 10) s.sendMessage("§7... e mais " + (items.size() - 10));
    }

    void skip(CommandSender s) {
        Bukkit.broadcastMessage("§e" + s.getName() + " pulou a música.");
        if (!loading) next();
    }

    void stop(CommandSender s) {
        queue.clear();
        player.stopTrack();
        Bukkit.broadcastMessage("§e" + s.getName() + " parou a música.");
    }

    boolean isPaused() { return player.isPaused(); }

    void pause(CommandSender s) {
        if (player.getPlayingTrack() == null) { s.sendMessage("§cNada tocando."); return; }
        player.setPaused(!player.isPaused());
        Bukkit.broadcastMessage("§e" + s.getName() + (player.isPaused() ? " pausou a música." : " continuou a música."));
    }

    void volume(CommandSender s, int v) {
        player.setVolume(Math.clamp(v, 0, 100));
        Bukkit.broadcastMessage("§eVolume: " + player.getVolume() + "%");
    }

    /** yt-dlp precisa estar em dia para acompanhar o YouTube; falha (ex.: instalado via pip) só vira aviso. */
    void updateYtDlp() {
        Thread.ofVirtual().start(() -> {
            try {
                plugin.getLogger().info("yt-dlp: " + String.join(" ", ytdlp.update()));
            } catch (Exception e) {
                plugin.getLogger().warning("yt-dlp -U falhou (atualize na mão): " + e.getMessage());
            }
        });
    }

    void shutdown() {
        ticker.shutdownNow();
        player.destroy();
        manager.shutdown();
        if (encoder != null) encoder.close();
    }

    private interface Task { void run() throws Exception; }

    private static void async(CommandSender s, Task task) {
        Thread.ofVirtual().start(() -> {
            try {
                task.run();
            } catch (Exception e) {
                s.sendMessage("§cFalhou: " + e.getMessage());
            }
        });
    }
}
