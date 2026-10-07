# The app. Postgres is a separate service — see compose.yml.
FROM python:3.12-slim

# spaCy, psycopg2-binary and pulp all ship wheels for this platform, so
# nothing here needs a compiler.
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir \
      https://github.com/explosion/spacy-models/releases/download/de_core_news_md-3.8.0/de_core_news_md-3.8.0-py3-none-any.whl

# The medium model by name, because that is what `matcher/phrase_finder.py`
# loads. Under `sm` it lemmatises `schreien` to `schreie`, and `spacy.load`
# raises rather than falling back — which is exactly the setup mistake this
# image exists to make impossible.

COPY . .

# chmod rather than trusting the build context: a Windows host has no
# executable bit to copy, and the entrypoint would arrive unrunnable.
RUN chmod +x /app/docker/entrypoint.sh

EXPOSE 8765

# The schema before the server — see docker/entrypoint.sh. It execs the CMD
# below, so `docker compose run app python main.py <anything>` still works and
# gets a migrated database too.
ENTRYPOINT ["/app/docker/entrypoint.sh"]

# Reachable inside the container network. Production requires a registered
# owner and exposes only the HTTPS proxy; local compose binds to loopback.
CMD ["python", "main.py", "serve", "--host", "0.0.0.0", "--port", "8765", \
     "--no-browser"]
