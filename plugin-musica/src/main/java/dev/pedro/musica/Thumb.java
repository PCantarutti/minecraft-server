package dev.pedro.musica;

import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.TextComponent;
import net.kyori.adventure.text.format.ShadowColor;
import net.kyori.adventure.text.format.TextColor;

import javax.imageio.ImageIO;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Miniatura desenhada com caracteres coloridos: a tela do Minecraft não mostra imagem de URL
 * (só com resource pack), então cada "pixel" é um █ com a cor média daquele pedaço da capa.
 */
final class Thumb {
    static final int W = 40, H = 15; // ponytail: proporção ajustada a olho para o █ da fonte do jogo
    private static final HttpClient HTTP = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5))
            .followRedirects(HttpClient.Redirect.NORMAL).build();
    private static final Map<String, Component> CACHE = Collections.synchronizedMap(new LinkedHashMap<>(32, 0.75f, true) {
        @Override protected boolean removeEldestEntry(Map.Entry<String, Component> e) { return size() > 64; }
    });

    static String youtube(String id) {
        return "https://i.ytimg.com/vi/" + id + "/mqdefault.jpg";
    }

    /** Bloqueia (rede): chamar fora da thread principal. Null se não houver capa ou falhar. */
    static Component render(String url) {
        if (url == null || url.isBlank()) return null;
        var hit = CACHE.get(url);
        if (hit != null) return hit;
        try {
            var res = HTTP.send(HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(8)).build(),
                    HttpResponse.BodyHandlers.ofInputStream());
            if (res.statusCode() != 200) return null;
            BufferedImage src;
            try (var in = res.body()) { src = ImageIO.read(in); }
            if (src == null) return null; // formato que o ImageIO não lê (ex.: webp)
            var img = new BufferedImage(W, H, BufferedImage.TYPE_INT_RGB);
            var g = img.createGraphics();
            g.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BILINEAR);
            g.setRenderingHint(RenderingHints.KEY_RENDERING, RenderingHints.VALUE_RENDER_QUALITY);
            // recorta para 16:9 no centro antes de reduzir (capa quadrada do SoundCloud fica com faixas)
            int cw = src.getWidth(), ch = cw * 9 / 16;
            if (ch > src.getHeight()) { ch = src.getHeight(); cw = ch * 16 / 9; }
            int x0 = (src.getWidth() - cw) / 2, y0 = (src.getHeight() - ch) / 2;
            g.drawImage(src, 0, 0, W, H, x0, y0, x0 + cw, y0 + ch, null);
            g.dispose();
            TextComponent.Builder out = Component.text().shadowColor(ShadowColor.none());
            for (int y = 0; y < H; y++) {
                if (y > 0) out.append(Component.newline());
                int run = 0, last = -1;
                for (int x = 0; x <= W; x++) { // junta pixels iguais vizinhos num só componente
                    int rgb = x < W ? img.getRGB(x, y) & 0xF0F0F0 : -2; // 4 bits por canal: bem menos componentes
                    if (rgb != last && run > 0) { out.append(Component.text("█".repeat(run), TextColor.color(last))); run = 0; }
                    last = rgb;
                    run++;
                }
            }
            var c = out.build();
            CACHE.put(url, c);
            return c;
        } catch (Exception e) {
            return null;
        }
    }
}
