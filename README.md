# spritz registry — server (v0.1)

Backend del catalogo/store per l'installazione di software su Haiku OS.
Modello **Opzione B**: il web genera install, il demone Haiku le esegue.

## Cosa fa già

- **Ingest misto git + cache.** Un *bàcaro* è un repo git di file YAML (*cichéti*).
  Il server li clona, li valida contro lo schema e li proietta in una cache DB
  interrogabile. Git = fonte di verità, DB = proiezione ricostruibile.
- **Catalogo pubblico.** `/search`, `/cicheto/{id}`.
- **Account email + password.** `/auth/register`, `/auth/login` (JWT bearer).
- **Resolve per il demone.** `/resolve/{id}?channel=&arch=` → url + sha256 + requires.
- **Libreria / coda (effetto Play Store).** L'utente accoda da browser
  (`POST /library/{id}`); il demone Haiku fa polling di `/library/pending`,
  installa, poi conferma con `/library/{id}/installed`.

## Avvio

```bash
pip install -r requirements.txt
python seed.py                 # popola la cache dal sample-bacaro locale
uvicorn app.main:app --reload  # poi apri http://localhost:8000/docs
```

`python test_flow.py` esercita l'intero flusso in-process senza rete.

## Struttura

```
app/
  schemas.py   formato cichéto (validazione, Pydantic)
  models.py    tabelle DB (cache cichéti, utenti, libreria)
  db.py        engine/sessione (SQLite ora, Postgres in prod)
  auth.py      bcrypt + JWT
  ingest.py    crawl bàcaro (git o cartella) → cache
  main.py      route FastAPI
sample-bacaro/ cichéto d'esempio (Genio)
```

## Endpoint principali

| Metodo | Path | Per chi |
|---|---|---|
| GET  | `/search?q=` | catalogo web |
| GET  | `/cicheto/{id}` | pagina-app |
| GET  | `/resolve/{id}?channel=&arch=` | demone Haiku |
| POST | `/auth/register` · `/auth/login` | account |
| POST | `/library/{id}` | accoda install (auth) |
| GET  | `/library/pending` | demone fa polling (auth) |
| POST | `/library/{id}/installed` | demone conferma (auth) |
| GET  | `/library` | "le mie app" (auth) |
| POST | `/ingest` | crawl bàcaro (da proteggere) |

## Prossimi passi (non in v1)

1. **Frontend web** del catalogo (la vetrina vera, con bottone che degrada:
   `spritz://` se il demone c'è, altrimenti bootstrap hpkg).
2. **Demone Haiku** che consuma `/library/pending` — chiude il cerchio Play Store.
3. **Crawler GitHub release** per i canali `ombra` (github-latest + pattern match).
4. **Tier di fiducia, firma manifest, transparency log** — fuori dal cichéto,
   asserzioni firmate dell'indice.
5. **Parte commerciale** (`spritz offri`, app a pagamento via Merchant of Record).
6. Auth sull'ingest, rate-limit, magic-link opzionale.

## Note di sicurezza già previste

- `sha256` obbligatorio sui canali pinned; verificato dal demone al download.
- I canali `github-latest` non pre-calcolano l'hash: il demone verifica al volo
  e logga l'hash visto (trade-off accettabile per i soli nightly).
- Trust tier e prezzo **non** stanno nel cichéto (file editabile nel repo git):
  vanno nell'indice firmato, così un fork non si auto-promuove.
