package dev.pedro.musica;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

/** Chama o yt-dlp, que acompanha as mudanças do YouTube muito mais rápido que qualquer lib Java. */
final class YtDlp {
    private final List<String> command;

    YtDlp(List<String> command) {
        this.command = command.isEmpty() ? List.of("yt-dlp") : command;
    }

    static boolean isYoutube(String url) {
        return url.matches("https?://([\\w-]+\\.)?(youtube\\.com|youtu\\.be)/.*");
    }

    /**
     * Baixa o melhor áudio para {@code dir} e devolve {título, caminho do arquivo}. Baixar pelo próprio
     * yt-dlp (em vez de pegar a URL e abrir no lavaplayer) porque o YouTube recusa (403) a URL fora dele.
     */
    String[] download(String query, java.nio.file.Path dir) throws Exception {
        var out = run(List.of("-f", "bestaudio", "--no-playlist", "--max-filesize", "200M", "--no-simulate", "--no-progress",
                "-o", dir.resolve("%(id)s.%(ext)s").toString(),
                "--print", "after_move:%(title)s", "--print", "after_move:filepath", query));
        if (out.size() < 2) throw new IllegalStateException("nada encontrado (ou arquivo maior que 200 MB)");
        return new String[]{out.get(out.size() - 2), out.get(out.size() - 1)};
    }

    /** Pares {título, URL do vídeo} de uma playlist, sem resolver o áudio (rápido). */
    List<String[]> playlist(String url) throws Exception {
        var out = run(List.of("--flat-playlist", "--print", "%(title)s", "--print", "%(url)s", url));
        List<String[]> items = new ArrayList<>();
        for (int i = 0; i + 1 < out.size(); i += 2) items.add(new String[]{out.get(i), out.get(i + 1)});
        return items;
    }

    /** Top {@code n} do YouTube para o texto: {id, título, duração, canal}. Sem baixar nada (~2 s). */
    List<String[]> search(String text, int n) throws Exception {
        return run(List.of("--flat-playlist", "--print", "%(id)s	%(title)s	%(duration_string)s	%(channel)s",
                "ytsearch" + n + ":" + text)).stream().map(l -> l.split("	", 4)).filter(r -> r.length == 4).toList();
    }

    List<String> update() throws Exception {
        return run(List.of("-U"));
    }

    private List<String> run(List<String> args) throws Exception {
        List<String> cmd = new ArrayList<>(command);
        cmd.addAll(List.of("--encoding", "utf-8", "--no-warnings"));
        cmd.addAll(args);
        var pb = new ProcessBuilder(cmd);
        pb.environment().put("PYTHONIOENCODING", "utf-8");
        Process p = pb.start();
        // stderr lido em paralelo para o processo não travar com buffer cheio
        var errText = new StringBuilder();
        var err = Thread.ofVirtual().start(() -> {
            try { errText.append(new String(p.getErrorStream().readAllBytes(), StandardCharsets.UTF_8)); } catch (IOException ignored) {}
        });
        String stdout = new String(p.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        if (!p.waitFor(120, TimeUnit.SECONDS)) { p.destroyForcibly(); throw new IllegalStateException("yt-dlp demorou demais"); }
        err.join();
        if (p.exitValue() != 0) {
            String msg = errText.toString().strip();
            throw new IllegalStateException(msg.isEmpty() ? "yt-dlp saiu com código " + p.exitValue() : msg.lines().reduce((a, b) -> b).orElse(msg));
        }
        return stdout.lines().filter(l -> !l.isBlank()).toList();
    }
}
