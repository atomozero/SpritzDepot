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
- **Layer repo-proxy (compatibile HaikuDepot).** `POST /repo/build` raggruppa i
  cichéti del canale stable per (vendor, arch), scarica gli hpkg dell'autore
  verificando lo sha256, e genera un catalogo HPKR con `package_repo`. Le route
  `/repo/{vendor}/{arch}/current/...` servono `repo.info`, il catalogo e gli
  hpkg, così basta aggiungere un URL in HaikuDepot. Un sub-repo per vendor,
  perché `package_repo` impone che tutti i pacchetti di un repo abbiano lo
  stesso vendor (vedi `docs/DECISIONS.md`).

## Avvio

```bash
pip install -r requirements.txt
python seed.py                 # popola la cache dal sample-bacaro locale
uvicorn app.main:app --reload  # poi apri http://localhost:8000/docs
```

`python test_flow.py` esercita l'intero flusso in-process senza rete.
`python test_security.py` verifica il gate admin su `/ingest` e il blocco prod.
`SPRITZ_PACKAGE_REPO_BIN=... python test_repo_proxy.py` prova il repo-proxy end
to end (richiede il tool `package_repo`, vedi `docs/SETUP-WSL.md`).

## Variabili d'ambiente

| Variabile | Default | A cosa serve |
|---|---|---|
| `SPRITZ_ENV` | `dev` | `dev` (fallback comodi, solo avvisi) o `prod` (gate attivo). |
| `SPRITZ_SECRET` | dev fallback | Chiave di firma dei JWT. In `prod` è obbligatoria. |
| `SPRITZ_ADMIN_TOKEN` | non impostata | Token admin per `/ingest` e `/repo/build` (header `X-Admin-Token`). Se manca, quegli endpoint sono chiusi (503), mai aperti. In `prod` è obbligatoria. |
| `SPRITZ_PACKAGE_REPO_BIN` | non impostata | Path al tool `package_repo` di Haiku (vedi `docs/SETUP-WSL.md`). Senza, il layer repo-proxy risponde 503; il resto del server gira lo stesso. |
| `SPRITZ_REPO_CACHE` | `packages-cache` | Dir dove il repo-proxy scarica gli hpkg e genera i cataloghi. Fuori dal sorgente, gitignored. |
| `SPRITZ_PUBLIC_BASE_URL` | `http://localhost:8000` | URL pubblico annunciato in `repo.info`. Deve essere raggiungibile da HaikuDepot. |

In `prod` l'app **non parte** se `SPRITZ_SECRET` o `SPRITZ_ADMIN_TOKEN` mancano o
sono ancora il default di sviluppo. In `dev` parte ma logga un avviso.

## Struttura

```
app/
  schemas.py     formato cichéto (validazione, Pydantic)
  models.py      tabelle DB (cache cichéti, utenti, libreria)
  db.py          engine/sessione (SQLite ora, Postgres in prod)
  config.py      env + gate sicurezza prod (secret, admin token, tool path)
  auth.py        bcrypt + JWT
  ingest.py      crawl bàcaro (git o cartella) → cache
  repo_proxy.py  layer compatibile HaikuDepot (fetch+verifica, HPKR, serve)
  main.py        route FastAPI
sample-bacaro/   cichéto d'esempio (Genio)
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
| POST | `/ingest` | crawl bàcaro (admin, `X-Admin-Token`) |
| POST | `/repo/build` | (ri)genera i sub-repo HaikuDepot (admin) |
| GET  | `/repo/{vendor}/{arch}/current/repo.info` | HaikuDepot |
| GET  | `/repo/{vendor}/{arch}/current/repo` | HaikuDepot (catalogo HPKR) |
| GET  | `/repo/{vendor}/{arch}/current/packages/{file}` | HaikuDepot (hpkg) |

## Prossimi passi (non in v1)

1. **Frontend web** del catalogo (la vetrina vera, con bottone che degrada:
   `spritz://` se il demone c'è, altrimenti bootstrap hpkg).
2. **Demone Haiku** che consuma `/library/pending` — chiude il cerchio Play Store.
3. **Crawler GitHub release** per i canali `ombra` (github-latest + pattern match).
4. **Tier di fiducia, firma manifest, transparency log** — fuori dal cichéto,
   asserzioni firmate dell'indice.
5. **Parte commerciale** (`spritz offri`, app a pagamento via Merchant of Record).
6. Rate-limit (login, register, ingest), HTTPS/HSTS, magic-link opzionale.

## Note di sicurezza

- **`/ingest` è admin-only** (`X-Admin-Token`); chiuso se il token non è
  configurato. La chiave JWT e il token admin vengono dall'ambiente, e in
  `prod` l'app rifiuta di partire senza (vedi Variabili d'ambiente).
- `sha256` obbligatorio sui canali pinned; verificato dal demone al download.
- I canali `github-latest` non pre-calcolano l'hash: il demone verifica al volo
  e logga l'hash visto (trade-off accettabile per i soli nightly).
- Trust tier e prezzo **non** stanno nel cichéto (file editabile nel repo git):
  vanno nell'indice firmato, così un fork non si auto-promuove.
