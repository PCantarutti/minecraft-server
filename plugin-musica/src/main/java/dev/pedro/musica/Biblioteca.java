package dev.pedro.musica;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.reflect.TypeToken;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Playlists do servidor, compartilhadas por todos, em plugins/Musica/biblioteca.json.
 * Cada faixa guarda o link (ou a busca), então tocar de novo baixa na hora, como qualquer item da fila.
 */
final class Biblioteca {
    record Faixa(String title, String url) {}

    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().create();
    private final Path file;
    private final Map<String, List<Faixa>> lists;

    Biblioteca(Path file) {
        this.file = file;
        Map<String, List<Faixa>> loaded = null;
        try {
            if (Files.exists(file))
                loaded = GSON.fromJson(Files.readString(file, StandardCharsets.UTF_8), new TypeToken<LinkedHashMap<String, List<Faixa>>>() {}.getType());
        } catch (Exception e) {
            throw new IllegalStateException("biblioteca.json ilegível; corrija ou apague o arquivo", e);
        }
        lists = loaded == null ? new LinkedHashMap<>() : loaded;
    }

    synchronized List<String> names() { return new ArrayList<>(lists.keySet()); }

    synchronized List<Faixa> get(String name) { return new ArrayList<>(lists.getOrDefault(name, List.of())); }

    /** Cria se não existir e adiciona as que ainda não estão lá. Devolve quantas entraram. */
    synchronized int add(String name, List<Faixa> faixas) {
        var l = lists.computeIfAbsent(name, k -> new ArrayList<>());
        int before = l.size();
        for (var f : faixas) if (l.stream().noneMatch(x -> x.url().equals(f.url()))) l.add(f);
        save();
        return l.size() - before;
    }

    synchronized void create(String name) {
        lists.putIfAbsent(name, new ArrayList<>());
        save();
    }

    synchronized void remove(String name, Faixa f) {
        var l = lists.get(name);
        if (l != null && l.remove(f)) save();
    }

    synchronized void delete(String name) {
        if (lists.remove(name) != null) save();
    }

    /** Grava num temporário e troca: queda no meio não corrompe o arquivo. */
    private void save() {
        try {
            Files.createDirectories(file.getParent());
            Path tmp = file.resolveSibling(file.getFileName() + ".tmp");
            Files.writeString(tmp, GSON.toJson(lists), StandardCharsets.UTF_8);
            Files.move(tmp, file, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
        } catch (Exception e) {
            throw new IllegalStateException("não consegui salvar a biblioteca: " + e.getMessage(), e);
        }
    }
}
