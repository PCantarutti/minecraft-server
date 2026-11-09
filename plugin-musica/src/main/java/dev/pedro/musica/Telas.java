package dev.pedro.musica;

import io.papermc.paper.dialog.Dialog;
import io.papermc.paper.dialog.DialogResponseView;
import io.papermc.paper.registry.data.dialog.ActionButton;
import io.papermc.paper.registry.data.dialog.DialogBase;
import io.papermc.paper.registry.data.dialog.action.DialogAction;
import io.papermc.paper.registry.data.dialog.body.DialogBody;
import io.papermc.paper.registry.data.dialog.input.DialogInput;
import io.papermc.paper.registry.data.dialog.type.DialogType;
import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.event.ClickCallback;
import net.kyori.adventure.text.event.ClickEvent;
import net.kyori.adventure.text.format.NamedTextColor;
import net.kyori.adventure.text.format.TextDecoration;
import org.bukkit.Bukkit;
import org.bukkit.entity.HumanEntity;
import org.bukkit.entity.Player;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.BiConsumer;
import java.util.function.Consumer;

/**
 * Telas do player (dialogs). Todas usam after_action "none": a tela atual fica aberta até o servidor
 * mandar a próxima (sem piscar). Por isso TODO botão termina abrindo outra tela, ou fechando (Fechar).
 */
final class Telas {
    private static final int RESULTS = 8;
    private static final ClickCallback.Options OPTS = ClickCallback.Options.builder()
            .uses(ClickCallback.UNLIMITED_USES).lifetime(Duration.ofMinutes(30)).build();
    private final MusicaPlugin plugin;

    Telas(MusicaPlugin plugin) {
        this.plugin = plugin;
    }

    /** "/music tela <ação>" (datapack antigo; mantido para quem estiver com a tela velha aberta). */
    void control(Player p, String args) {
        custom(p, args.split(" ", 2)[0], null);
    }

    /**
     * Botões da tela "♪ Música" do datapack (ações custom "musica:<id>"). Cada um faz o mesmo que o
     * botão do player dinâmico e abre o player atualizado.
     */
    void custom(Player p, String id, DialogResponseView v) {
        var m = plugin.music;
        switch (id) {
            case "buscar" -> search(p, v == null ? "" : text(v, "q"));
            case "pause" -> { m.pause(p); player(p); }
            case "skip" -> { m.skip(p); playerLater(p); }
            case "shuffle" -> { m.shuffle(p); player(p); }
            case "stop" -> { m.stop(p); player(p); }
            case "salvar" -> saveCurrent(p);
            case "fila" -> queue(p);
            case "playlists", "biblioteca" -> library(p);
            case "volume" -> volumeScreen(p);
            case "fechar" -> { forget(p); p.closeDialog(); }
            default -> player(p);
        }
    }

    // --- player ---

    /**
     * Sem atualização automática: reenviar a tela apagaria o que está sendo digitado na busca.
     * O tempo ao vivo fica na barra do topo; qualquer botão traz a tela atualizada.
     */
    /** Quem está com o player aberto. Recebe a tela de novo quando a música muda (não a cada segundo: apagaria a busca digitada). */
    private final Set<UUID> open = ConcurrentHashMap.newKeySet();

    void player(Player p) { render(p, false); }

    /** Chamado pelo Music quando uma faixa começa ou a fila acaba. */
    void refreshOpen() {
        Bukkit.getScheduler().runTask(plugin, () -> {
            for (var id : open) {
                var p = Bukkit.getPlayer(id);
                if (p == null) open.remove(id); else render(p, true);
            }
        });
    }

    void forget(Player p) { open.remove(p.getUniqueId()); }

    private void render(Player p, boolean refresh) {
        Thread.ofVirtual().start(() -> {
            var m = plugin.music;
            var now = m.playing();
            List<DialogBody> body = new ArrayList<>();
            if (now != null) {
                var thumb = Thumb.render(m.nowThumb());
                if (thumb != null) body.add(DialogBody.plainMessage(thumb, 400));
                body.add(DialogBody.plainMessage(Component.text(String.valueOf(now.getUserData()), NamedTextColor.WHITE, TextDecoration.BOLD), 400));
                body.add(DialogBody.plainMessage(progress(now.getPosition(), now.getDuration(), now.getInfo().isStream, m.isPaused()), 400));
            } else {
                body.add(DialogBody.plainMessage(Component.text(m.isLoading() ? "Carregando..." : "Nada tocando.", NamedTextColor.WHITE), 400));
            }
            String next = m.nextTitle();
            int n = m.queued().size();
            body.add(DialogBody.plainMessage(Component.text(next == null ? "Fila vazia" : "Próxima: " + cut(next, 40)
                    + (n > 1 ? "  ·  +" + (n - 1) + " na fila" : ""), NamedTextColor.DARK_GRAY), 400));
            var d = playerDialog(body);
            Bukkit.getScheduler().runTask(plugin, () -> {
                if (refresh && !open.contains(p.getUniqueId())) return; // saiu do player enquanto montava
                open.add(p.getUniqueId());
                p.showDialog(d);
            });
        });
    }

    /** "1:23  ━━━━━●────────  3:45": foto do momento em que a tela abriu; ao vivo fica na barra do topo. */
    private static Component progress(long pos, long dur, boolean live, boolean paused) {
        if (live || dur <= 0) return Component.text("● ao vivo", NamedTextColor.RED);
        int w = 26, done = (int) Math.min(w, w * pos / dur);
        return Component.text((paused ? "⏸ " : "") + Music.clock(pos) + "  ", NamedTextColor.GRAY)
                .append(Component.text("━".repeat(done), NamedTextColor.LIGHT_PURPLE))
                .append(Component.text("●", NamedTextColor.WHITE))
                .append(Component.text("─".repeat(w - done), NamedTextColor.DARK_GRAY))
                .append(Component.text("  " + Music.clock(dur), NamedTextColor.GRAY));
    }

    /** Mesmo layout da tela "♪ Música" do datapack (controle.json): campo + 3x3 botões. */
    private Dialog playerDialog(List<DialogBody> body) {
        var m = plugin.music;
        // Buscar é o primeiro botão: no campo, Tab leva até ele e Enter clica.
        var q = DialogInput.text("q", Component.text("Buscar música ou colar link")).width(310).maxLength(300).build();
        List<ActionButton> b = List.of(
                btnV("Buscar", "Procura o que está no campo", 100, (pl, v) -> search(pl, text(v, "q"))),
                btn(m.isPaused() || m.playing() == null ? "▶ Continuar" : "⏸ Pausar", null, 100, pl -> custom(pl, "pause", null)),
                btn("» Próxima", null, 100, pl -> custom(pl, "skip", null)),
                btn("⤨ Aleatório", "Embaralha a fila", 100, pl -> custom(pl, "shuffle", null)),
                btn("■ Parar", "Para e limpa a fila", 100, pl -> custom(pl, "stop", null)),
                btn("♥ Salvar", "Salva a música atual numa playlist", 100, this::saveCurrent),
                btn("Fila", null, 100, this::queue),
                btn("Playlists", null, 100, this::library),
                btn("Volume " + m.volume(), null, 100, this::volumeScreen));
        return dialog("♪ Música do servidor", body, List.of(q), b, 3, btn("Fechar", null, 100, HumanEntity::closeDialog));
    }

    private void saveCurrent(Player p) {
        var m = plugin.music;
        var now = m.playing();
        if (now == null || m.nowUrl() == null) notice(p, "Nada tocando para salvar.");
        else saveTo(p, List.of(new Biblioteca.Faixa(String.valueOf(now.getUserData()), m.nowUrl())));
    }

    private void playerLater(Player p) {
        Bukkit.getScheduler().runTaskLater(plugin, () -> player(p), 20); // 1 s: a próxima começar a carregar
    }

    private void volumeScreen(Player p) {
        var m = plugin.music;
        var v = DialogInput.numberRange("v", Component.text("Volume"), 0, 100).step(5f).initial((float) m.volume()).width(310).build();
        show(p, dialog("Volume", List.of(DialogBody.plainMessage(Component.text(
                        "Vale para todos. Cada um também ajusta \"Música\" no menu do voice chat (V).", NamedTextColor.GRAY), 310)),
                List.of(v), List.of(
                        btnV("Aplicar", null, 150, (pl, r) -> {
                            Float vol = r.getFloat("v");
                            if (vol != null) m.volume(pl, Math.round(vol));
                            player(pl);
                        }),
                        btn("← Player", null, 150, this::player)), 2, null));
    }

    // --- busca: lista -> prévia com capa -> tocar ---

    private void search(Player p, String text) {
        if (text.isEmpty()) { notice(p, "Digite o nome da música ou cole um link."); return; }
        if (text.startsWith("http://") || text.startsWith("https://")) {
            plugin.music.enqueue(p, text, YtDlp.isYoutube(text) && text.contains("list="));
            playerLater(p);
            return;
        }
        Thread.ofVirtual().start(() -> {
            try {
                var rs = plugin.music.ytdlp().search(text, RESULTS);
                if (rs.isEmpty()) notice(p, "Nada encontrado para \"" + text + "\".");
                else show(p, results(text, rs));
            } catch (Exception e) {
                notice(p, "A busca falhou: " + e.getMessage());
            }
        });
    }

    private Dialog results(String text, List<String[]> rs) {
        List<ActionButton> b = new ArrayList<>();
        Dialog[] self = new Dialog[1]; // a prévia volta para esta mesma lista
        for (String[] r : rs) // {id, título, duração, canal}
            b.add(ActionButton.create(
                    Component.text(cut(r[1], 44) + "  ").append(Component.text(r[2], NamedTextColor.GRAY)),
                    Component.text(r[1] + "\n" + r[3]), 310,
                    DialogAction.customClick((v, who) -> { if (who instanceof Player p) preview(p, r, self[0]); }, OPTS)));
        self[0] = dialog("Resultados: " + cut(text, 30),
                List.of(DialogBody.plainMessage(Component.text("Escolha a versão. A próxima tela mostra a capa.", NamedTextColor.GRAY), 310)),
                List.of(), b, 1, btn("← Player", null, 200, this::player));
        return self[0];
    }

    private void preview(Player p, String[] r, Dialog list) {
        Thread.ofVirtual().start(() -> {
            var thumb = Thumb.render(Thumb.youtube(r[0]));
            List<DialogBody> body = new ArrayList<>();
            if (thumb != null) body.add(DialogBody.plainMessage(thumb, 400));
            body.add(DialogBody.plainMessage(Component.text(r[1], NamedTextColor.WHITE, TextDecoration.BOLD), 400));
            body.add(DialogBody.plainMessage(Component.text(r[3] + "  ·  " + r[2], NamedTextColor.GRAY), 400));
            String url = "https://www.youtube.com/watch?v=" + r[0];
            var m = plugin.music;
            var b = List.of(
                    btn("⤴ Tocar a seguir", "Entra na frente da fila", 150, pl -> { m.add(pl, r[1], url, true); player(pl); }),
                    btn("▶ Fim da fila", null, 150, pl -> { m.add(pl, r[1], url, false); player(pl); }),
                    btn("♥ Salvar em playlist", null, 150, pl -> saveTo(pl, List.of(new Biblioteca.Faixa(r[1], url)))),
                    ActionButton.create(Component.text("← Outras versões"), null, 150, DialogAction.staticAction(ClickEvent.showDialog(list))));
            show(p, dialog("Prévia", body, List.of(), b, 2, null));
        });
    }

    // --- fila ---

    void queue(Player p) {
        var m = plugin.music;
        var items = m.queued();
        List<DialogBody> body = new ArrayList<>();
        if (items.isEmpty()) {
            body.add(DialogBody.plainMessage(Component.text("Fila vazia.", NamedTextColor.GRAY), 400));
        } else {
            // ponytail: a fila inteira num bloco de texto; a tela rola sozinha quando passa da altura
            var list = Component.text().content(items.size() + " na fila").color(NamedTextColor.GOLD);
            for (int i = 0; i < items.size(); i++)
                list.append(Component.newline()).append(Component.text((i + 1) + ". ", NamedTextColor.GRAY))
                        .append(Component.text(items.get(i).title(), NamedTextColor.WHITE));
            body.add(DialogBody.plainMessage(list.build(), 400));
        }
        List<ActionButton> b = new ArrayList<>();
        if (items.size() > 1) {
            b.add(btn("⤴ Escolher a próxima", null, 150, this::pickNext));
            b.add(btn("⤨ Aleatorizar", null, 150, pl -> { m.shuffle(pl); queue(pl); }));
        }
        if (!items.isEmpty())
            b.add(btn("♥ Salvar como playlist", null, 150, pl -> saveTo(pl, items.stream()
                    .map(e -> new Biblioteca.Faixa(e.title(), e.track() != null ? e.track().getInfo().uri : e.query())).toList())));
        b.add(btn("⟳ Atualizar", null, 150, this::queue));
        show(p, dialog("Fila", body, List.of(), b, 2, btn("← Player", null, 200, this::player)));
    }

    /** Um botão por faixa da fila: clicar passa ela para a frente. */
    private void pickNext(Player p) {
        var items = plugin.music.queued();
        List<ActionButton> b = new ArrayList<>();
        for (int i = 0; i < Math.min(items.size(), 200); i++) { // ponytail: teto de 200 botões; Aleatorizar cobre filas maiores
            var e = items.get(i);
            b.add(ActionButton.create(Component.text((i + 1) + ". ", NamedTextColor.GRAY).append(Component.text(cut(e.title(), 46))),
                    null, 310, DialogAction.customClick((v, who) -> {
                        if (!(who instanceof Player pl)) return;
                        plugin.music.moveNext(pl, e);
                        queue(pl);
                    }, OPTS)));
        }
        show(p, dialog("Qual toca a seguir?", List.of(), List.of(), b, 1, btn("← Fila", null, 200, this::queue)));
    }

    // --- playlists salvas ---

    private Biblioteca lib() { return plugin.biblioteca; }

    void library(Player p) {
        var names = lib().names();
        var body = List.of(DialogBody.plainMessage(Component.text(names.isEmpty()
                ? "Nenhuma playlist ainda. Crie uma abaixo ou use ♥ Salvar no player."
                : "Playlists do servidor (todo mundo vê e edita).", NamedTextColor.GRAY), 310));
        List<ActionButton> b = new ArrayList<>();
        for (var name : names)
            b.add(btn(cut(name, 20) + "  (" + lib().get(name).size() + ")", null, 150, pl -> playlist(pl, name)));
        b.add(btnV("＋ Nova playlist", "Usa o nome do campo", 150, (pl, v) -> {
            String name = text(v, "nome");
            if (name.isEmpty()) { notice(pl, "Digite um nome para a playlist."); return; }
            lib().create(name);
            playlist(pl, name);
        }));
        var nome = DialogInput.text("nome", Component.text("Nome da nova playlist")).width(310).maxLength(40).build();
        show(p, dialog("Playlists", body, List.of(nome), b, 2, btn("← Player", null, 200, this::player)));
    }

    /**
     * 4 colunas. 1ª linha: a playlist inteira. Depois uma linha por faixa:
     * [título = tocar agora] [+ fim da fila] [⤴ a seguir] [✖ remover].
     */
    private void playlist(Player p, String name) {
        var faixas = lib().get(name);
        var m = plugin.music;
        List<ActionButton> b = new ArrayList<>();
        if (!faixas.isEmpty()) {
            b.add(btn("▶ Tocar tudo (" + faixas.size() + ")", "Tudo no fim da fila", 200, pl -> { m.addAll(pl, lib().get(name), false, false); playerLater(pl); }));
            b.add(btn("⤨", "Tocar tudo em ordem aleatória", 24, pl -> { m.addAll(pl, lib().get(name), true, false); playerLater(pl); }));
            b.add(btn("⤴", "Tudo a seguir (antes do resto da fila)", 24, pl -> { m.addAll(pl, lib().get(name), false, true); playerLater(pl); }));
            b.add(btn("✖", "Apagar a playlist inteira", 24, pl -> confirmDelete(pl, name)));
        }
        for (int i = 0; i < Math.min(faixas.size(), 150); i++) { // ponytail: teto de 150 linhas na tela
            var f = faixas.get(i);
            b.add(ActionButton.create(Component.text((i + 1) + ". ", NamedTextColor.GRAY).append(Component.text(cut(f.title(), 30))),
                    Component.text("Tocar agora: " + f.title()), 200,
                    DialogAction.customClick((v, who) -> {
                        if (!(who instanceof Player pl)) return;
                        open.remove(pl.getUniqueId());
                        m.playNow(pl, f.title(), f.url());
                        player(pl);
                    }, OPTS)));
            b.add(btn("+", "Adicionar no fim da fila", 24, pl -> { m.add(pl, f.title(), f.url(), false); playlist(pl, name); }));
            b.add(btn("⤴", "Tocar a seguir", 24, pl -> { m.add(pl, f.title(), f.url(), true); playlist(pl, name); }));
            b.add(btn("✖", "Remover desta playlist", 24, pl -> { lib().remove(name, f); playlist(pl, name); }));
        }
        var body = List.of(DialogBody.plainMessage(Component.text(faixas.isEmpty()
                ? "Vazia. Use ♥ Salvar no player, na prévia ou na fila."
                : "Clique no nome para tocar agora. Passe o mouse nos ícones para ver o que fazem.", NamedTextColor.GRAY), 310));
        if (faixas.isEmpty()) b.add(btn("✖ Apagar playlist", null, 200, pl -> confirmDelete(pl, name)));
        show(p, dialog("♫ " + name, body, List.of(), b, faixas.isEmpty() ? 1 : 4, btn("← Playlists", null, 200, this::library)));
    }

    private void confirmDelete(Player p, String name) {
        var yes = btn("Apagar", null, 150, pl -> { lib().delete(name); library(pl); });
        var no = btn("Cancelar", null, 150, pl -> playlist(pl, name));
        show(p, Dialog.create(f -> f.empty()
                .base(base("Apagar \"" + cut(name, 30) + "\"?", List.of(DialogBody.plainMessage(
                        Component.text(lib().get(name).size() + " faixa(s). Não dá para desfazer."), 310)), List.of()))
                .type(DialogType.confirmation(yes, no))));
    }

    /** Escolher em qual playlist salvar (ou criar uma nova com o nome do campo). */
    private void saveTo(Player p, List<Biblioteca.Faixa> faixas) {
        List<ActionButton> b = new ArrayList<>();
        for (var name : lib().names())
            b.add(btn(cut(name, 22), null, 150, pl -> saved(pl, name, faixas)));
        b.add(btnV("＋ Criar e salvar", "Usa o nome do campo", 150, (pl, v) -> {
            String name = text(v, "nome");
            if (name.isEmpty()) notice(pl, "Digite um nome para a playlist.");
            else saved(pl, name, faixas);
        }));
        var body = List.of(DialogBody.plainMessage(Component.text(faixas.size() == 1
                ? faixas.getFirst().title() : faixas.size() + " faixas", NamedTextColor.WHITE), 310));
        var nome = DialogInput.text("nome", Component.text("Ou crie uma nova")).width(310).maxLength(40).build();
        show(p, dialog("Salvar em qual playlist?", body, List.of(nome), b, 2, btn("← Player", null, 200, this::player)));
    }

    private void saved(Player p, String name, List<Biblioteca.Faixa> faixas) {
        int added = lib().add(name, faixas);
        p.sendActionBar(Component.text(added == 0 ? "Já estava em " + name : "♥ Salvo em " + name, NamedTextColor.LIGHT_PURPLE));
        player(p);
    }

    // --- util ---

    private void notice(Player p, String msg) {
        show(p, Dialog.create(f -> f.empty()
                .base(base("Música", List.of(DialogBody.plainMessage(Component.text(msg), 310)), List.of()))
                .type(DialogType.notice(btn("← Player", null, 200, this::player)))));
    }

    private static DialogBase base(String title, List<? extends DialogBody> body, List<DialogInput> inputs) {
        return DialogBase.builder(Component.text(title)).body(body).inputs(inputs).canCloseWithEscape(true)
                .pause(false).afterAction(DialogBase.DialogAfterAction.NONE).build(); // "none" exige pause=false
    }

    private static Dialog dialog(String title, List<? extends DialogBody> body, List<DialogInput> inputs,
                                 List<ActionButton> buttons, int columns, ActionButton exit) {
        return Dialog.create(f -> f.empty().base(base(title, body, inputs)).type(DialogType.multiAction(buttons, exit, columns)));
    }

    private ActionButton btn(String label, String tip, int width, Consumer<Player> on) {
        return btnV(label, tip, width, (p, v) -> on.accept(p));
    }

    private ActionButton btnV(String label, String tip, int width, BiConsumer<Player, DialogResponseView> on) {
        return ActionButton.create(Component.text(label), tip == null ? null : Component.text(tip), width,
                DialogAction.customClick((v, who) -> {
                    if (!(who instanceof Player p)) return;
                    open.remove(p.getUniqueId()); // saiu do player; se o destino for o player, ele volta
                    on.accept(p, v);
                }, OPTS));
    }

    private static String text(DialogResponseView v, String key) {
        String s = v.getText(key);
        return s == null ? "" : s.trim();
    }

    private void show(Player p, Dialog d) {
        Bukkit.getScheduler().runTask(plugin, () -> p.showDialog(d));
    }

    private static String cut(String s, int n) {
        return s.length() <= n ? s : s.substring(0, n - 1) + "…";
    }
}
