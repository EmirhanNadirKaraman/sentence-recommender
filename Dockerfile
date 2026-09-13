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

EXPOSE 8765

# 0.0.0.0 so the port mapping reaches it. There is no authentication, which
# is why compose publishes it on 127.0.0.1 only.
CMD ["python", "main.py", "serve", "--host", "0.0.0.0", "--port", "8765", \
     "--no-browser"]
