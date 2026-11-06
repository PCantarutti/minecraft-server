FROM python:3.12-slim

# CLI do Docker + plugin do compose vindos das imagens oficiais, em vez de
# baixar binário solto. O painel precisa dos dois: `docker start/stop/logs`
# para o ciclo de vida, e `docker compose up -d` para aplicar mudança de
# configuração (que exige recriar o container).
COPY --from=docker:29.3.1-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker/compose-bin:v5.6.1 /docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose

# rclone: envio de backup pro Google Drive. zip/unzip: upload e download de mundo.
RUN apt-get update \
 && apt-get install -y --no-install-recommends rclone zip unzip tar gzip curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# htmx vendorizado: o painel vive numa tailnet e a rede deste servidor filtra
# domínios. Buscar de CDN em runtime seria um ponto de falha a mais.
RUN mkdir -p static \
 && curl -fsSL https://cdnjs.cloudflare.com/ajax/libs/htmx/2.0.4/htmx.min.js \
      -o static/htmx.min.js \
 && test -s static/htmx.min.js

# Inter self-hospedada. A pilha de fontes do sistema renderiza Segoe UI nesta
# máquina — humanista, mais larga, numerais diferentes — enquanto a referência
# usa um grotesco neutro. Sem o arquivo, reordenar a pilha não muda nada.
RUN for w in 400 600 700; do \
      curl -fsSL "https://cdn.jsdelivr.net/npm/@fontsource/inter@5.0.16/files/inter-latin-$w-normal.woff2" \
        -o "static/inter-$w.woff2" && test -s "static/inter-$w.woff2"; \
    done

COPY . .

EXPOSE 8080
CMD ["python", "-u", "app.py"]
