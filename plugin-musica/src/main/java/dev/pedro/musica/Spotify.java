package dev.pedro.musica;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.regex.Pattern;

/** Só lê nomes de faixas (Web API, client credentials). O áudio vem do YouTube. */
final class Spotify {
    private static final Pattern LINK = Pattern.compile("open\\.spotify\\.com/(?:intl-\\w+/)?(track|playlist|album)/(\\w+)");
    private final HttpClient http = HttpClient.newHttpClient();
    private final String id, secret;

    Spotify(String id, String secret) {
        this.id = id;
        this.secret = secret;
    }

    /** Devolve "artista - música" para cada faixa do link. */
    List<String> trackNames(String url) throws Exception {
        if (id.isBlank() || secret.isBlank()) throw new IllegalStateException("configure spotify.client-id/secret no config.yml");
        var m = LINK.matcher(url);
        if (!m.find()) throw new IllegalArgumentException("link do Spotify não reconhecido");
        String token = token();
        String kind = m.group(1), key = m.group(2);
        List<String> out = new ArrayList<>();
        if (kind.equals("track")) {
            out.add(name(get("https://api.spotify.com/v1/tracks/" + key, token)));
            return out;
        }
        String next = "https://api.spotify.com/v1/" + kind + "s/" + key + "/tracks?limit=50";
        while (next != null) {
            JsonObject page = get(next, token);
            for (var item : page.getAsJsonArray("items")) {
                var o = item.getAsJsonObject();
                var track = o.has("track") ? o.get("track") : o; // playlist embrulha em "track"; álbum não
                if (track != null && track.isJsonObject()) out.add(name(track.getAsJsonObject()));
            }
            next = page.get("next").isJsonNull() ? null : page.get("next").getAsString();
        }
        return out;
    }

    private static String name(JsonObject t) {
        String artist = t.getAsJsonArray("artists").get(0).getAsJsonObject().get("name").getAsString();
        return artist + " - " + t.get("name").getAsString();
    }

    private String token() throws Exception {
        String basic = Base64.getEncoder().encodeToString((id + ":" + secret).getBytes(StandardCharsets.UTF_8));
        var req = HttpRequest.newBuilder(URI.create("https://accounts.spotify.com/api/token"))
                .header("Authorization", "Basic " + basic)
                .header("Content-Type", "application/x-www-form-urlencoded")
                .POST(HttpRequest.BodyPublishers.ofString("grant_type=" + URLEncoder.encode("client_credentials", StandardCharsets.UTF_8)))
                .build();
        return parse(http.send(req, HttpResponse.BodyHandlers.ofString())).get("access_token").getAsString();
    }

    private JsonObject get(String url, String token) throws Exception {
        var req = HttpRequest.newBuilder(URI.create(url)).header("Authorization", "Bearer " + token).build();
        return parse(http.send(req, HttpResponse.BodyHandlers.ofString()));
    }

    private static JsonObject parse(HttpResponse<String> r) {
        if (r.statusCode() / 100 != 2) throw new IllegalStateException("HTTP " + r.statusCode() + ": " + r.body());
        return JsonParser.parseString(r.body()).getAsJsonObject();
    }
}
