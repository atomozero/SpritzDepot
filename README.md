# spritz registry — server (v0.1)

Backend del catalogo/store per l'installazione di software su Haiku OS.
Modello **Opzione B**: il web genera install, il demone Haiku le esegue.

## Cosa fa già

- **Ingest misto git + cache.** Un *bàcaro* è un repo git di file YAML (*cichéti*).
  Il server li clona, li valida contro lo schema e li proietta in una cache DB
  interrogabile. Git = fonte di verità, DB = proiezione ricostruibile. L'ingest
  fa pruning: i cichéti spariti da un bàcaro vengono rimossi dalla cache, così
  la proiezione resta fedele. L'attribuzione al bàcaro usa lo slug del crawl,
  non il packager dichiarato, così un cichéto non può rubare le righe altrui.
- **Catalogo pubblico.** `/search`, `/cicheto/{id}`.
- **Account email + password.** `/auth/register`, `/auth/login` (JWT bearer).
- **Resolve per il demone.** `/resolve/{id}?channel=&arch=` → url + sha256 + requires.
  Per il canale **ombra** (`source: github-latest`) gli URL sono risolti al volo
  sull'ultima release GitHub dell'autore, senza sha256 pre-calcolato (il client
  verifica l'hash al download). È la cosa che un repo HPKR statico non può fare.
- **Libreria / coda (effetto Play Store).** L'utente accoda da browser
  (`POST /library/{id}`); il demone Haiku fa polling di `/library/pending`,
  installa, poi conferma con `/library/{id}/installed`.
- **Layer repo-proxy (compatibile HaikuDepot).** Raggruppa i cichéti del canale
  stable per (vendor, arch), scarica gli hpkg dell'autore verificando lo sha256,
  e genera un catalogo HPKR con `package_repo`. Le route
  `/repo/{vendor}/{arch}/current/...` servono `repo.info` (con un `identifier`
  UUID stabile), il catalogo e gli hpkg, così basta aggiungere un URL in
  HaikuDepot. Il rebuild è automatico all'`/ingest` (oppure `POST /repo/build`
  on demand). Un sub-repo per vendor, perché `package_repo` impone che tutti i
  pacchetti di un repo abbiano lo stesso vendor (vedi `docs/DECISIONS.md`).
- **Frontend web (server-rendered, in italiano).** Home con ricerca e filtri
  (categoria, bàcaro), pagina app con i canali, la nota bridge HaikuPorts e il
  bottone che degrada: prova a contattare il client nativo (`spritz://` in un
  clic) e altrimenti offre il repository da aggiungere in HaikuDepot. I badge
  categoria e bàcaro sono cliccabili; c'è una pagina `/categories` per sfogliare.
  Template Jinja leggeri, pensati per WebPositive.
- **Icone delle app** (`/icon/{id}`). Estrae l'icona HVIF dall'hpkg dell'app, la
  converte in PNG (via `hvif2png`) e la mette in cache. On-demand, con un limite
  di dimensione per non scaricare hpkg enormi solo per l'icona: oltre soglia (o
  senza il tool) il frontend mostra un placeholder con l'iniziale.
- **Pagina di pubblicazione** (`/publish`, autenticata). L'autore compila un
  form e ottiene un file cichéto YAML da mettere nel proprio bàcaro git. Non
  scrive nulla lato server (git resta la fonte di verità): valida con lo stesso
  schema dell'ingest, quindi il file generato si re-ingesta sempre pulito.
- **Login nel browser** (`/login`). Form accedi/registrati: il sito chiama
  `/auth/login` o `/auth/register`, salva il JWT in localStorage e lo allega da
  solo alle pagine protette (libreria, pubblica). Niente piu' token da incollare;
  l'header mostra "Accedi" o l'email con "Esci".
- **Pagina admin** (`/admin`). Incolli il token admin e gestisci i bàcari dal
  web: ingest, ri-crawl in un clic (l'URL git resta memorizzato), rebuild dei
  repo HaikuDepot, elenco con esito dell'ultimo crawl. La pagina è visibile ma
  inerte senza token; ogni azione è verificata dal server.
- **Canale ombra (segue l'autore).** Per i canali `github-latest`, spritz
  risolve l'ultima release GitHub dell'autore al volo: trova gli asset .hpkg per
  arch col pattern del cichéto e ne restituisce gli URL. Non costruisce
  pacchetti e non pre-calcola l'hash (lo verifica il client al download).
- **Canale hpkr-repo (repo di terze parti).** Per un repository Haiku di terze
  parti (NON HaikuPorts: BeSly, Fat Elk, il server dell'autore), spritz legge il
  catalogo HPKR (`hpkr.py`, parser in puro Python verificato contro l'output di
  `package_repo`), trova il pacchetto e ne compone l'URL `baseUrl + nome-versione-arch.hpkg`.
  E' il gap che HaikuDepot non copre di default. `POST /repo/import-hpkr`
  (admin) importa in un colpo tutto un repo di terze parti: legge il catalogo e
  crea un cichéto hpkr-repo per ogni pacchetto (rifiuta gli URL HaikuPorts, che
  vanno in bridge).

## Avvio

```bash
pip install -r requirements.txt
python seed.py                 # popola la cache dal sample-bacaro locale
uvicorn app.main:app --reload  # poi apri http://localhost:8000/docs
```

`python test_flow.py` esercita l'intero flusso in-process senza rete.
`python test_security.py` verifica auth, rate-limit, validazione e blocco prod.
`python test_frontend.py` controlla il rendering delle pagine.
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
| `SPRITZ_CORS_ORIGINS` | localhost | Origini CORS ammesse (CSV) per il frontend web. Mai `*`. |
| `SPRITZ_GITHUB_TOKEN` | non impostata | Token GitHub opzionale per il crawler ombra (alza il rate limit dell'API release). |
| `SPRITZ_UPLOAD_DIR` | `packages-cache/assets` | Dir dove finiscono icone/screenshot caricati. Gitignored. |
| `SPRITZ_DB_URL` | `sqlite:///./spritz.db` | URL del database. In prod puntalo a Postgres (vedi `migrations/`). |
| `SPRITZ_HVIF2PNG_BIN` | non impostata | Path al tool `hvif2png` di Haiku per estrarre le icone dagli hpkg (vedi `docs/SETUP-WSL.md`). Senza, `/icon` risponde 404 e il frontend usa il placeholder. |
| `SPRITZ_MAX_HPKG_ICON_BYTES` | `20971520` (20MB) | Oltre questa dimensione spritz non scarica l'hpkg solo per estrarne l'icona. |

In `prod` l'app **non parte** se `SPRITZ_SECRET` o `SPRITZ_ADMIN_TOKEN` mancano o
sono ancora il default di sviluppo. In `dev` parte ma logga un avviso. In `prod`
l'HTTP viene rediretto a HTTPS (con HSTS); in `dev` `http://localhost` resta
valido. Login/register/ingest sono rate-limited (429 oltre la soglia).

## Struttura

```
app/
  schemas.py     formato cichéto (validazione, Pydantic)
  models.py      tabelle DB (cache cichéti, utenti, libreria)
  db.py          engine/sessione (SQLite ora, Postgres in prod)
  config.py      env + gate sicurezza prod (secret, admin token, tool path)
  auth.py        bcrypt + JWT
  ingest.py      crawl bàcaro (git o cartella) → cache
  ombra.py       resolver canale ombra (ultima release GitHub dell'autore)
  hpkr.py        lettore catalogo HPKR (risolve hpkg da repo Haiku di terze parti)
  hvif.py        estrae l'icona HVIF da un hpkg e la converte in PNG (via hvif2png)
  repo_proxy.py  layer compatibile HaikuDepot (fetch+verifica, HPKR, serve)
  main.py        route FastAPI (API + frontend)
  templates/     pagine Jinja (home, app, get-spritz)
  static/        CSS + JS del frontend (degrading button)
sample-bacaro/   cichéto d'esempio (Genio)
```

## Endpoint principali

| Metodo | Path | Per chi |
|---|---|---|
| GET  | `/search?q=&category=&bacaro=&limit=&offset=` | catalogo (filtri + paginazione, ritorna `{total, results}`) |
| GET  | `/api/categories` | categorie con conteggi |
| GET  | `/bacari` | bàcari noti (conteggi, ultimo ingest) |
| GET  | `/health` | liveness/readiness (503 se il DB non risponde) |
| GET  | `/stats` | conteggi del catalogo (cichéti, bàcari, per categoria/canale) |
| GET  | `/cicheto/{id}` | pagina-app |
| GET  | `/resolve/{id}?channel=&arch=` | demone Haiku |
| POST | `/auth/register` · `/auth/login` | account (rate-limited) |
| POST | `/auth/change-password` · `/auth/logout-all` | account (revoca i token) |
| GET  | `/publish` | form di pubblicazione (web) |
| POST | `/publish` | genera cichéto YAML (auth) |
| POST | `/upload/image` | carica icona/screenshot, ritorna URL (auth) |
| GET  | `/assets/{file}` | serve un'immagine caricata |
| GET  | `/icon/{id}` | icona dell'app estratta dall'hpkg (PNG, cache) |
| GET  | `/login` | pagina di accesso/registrazione (web) |
| GET  | `/library-page` | pagina "le mie app" (web) |
| POST | `/library/{id}` | accoda install (auth) |
| GET  | `/library/pending` | demone fa polling (auth) |
| POST | `/library/{id}/installed` | demone conferma (auth) |
| GET  | `/library` | "le mie app" (auth) |
| POST | `/ingest` | crawl bàcaro + auto-rebuild repo (admin, `X-Admin-Token`) |
| POST | `/repo/build` | rebuild completo dei sub-repo HaikuDepot (admin) |
| GET  | `/admin` | pagina admin (web) |
| GET  | `/admin/bacari` | bàcari memorizzati con URL ed esito (admin) |
| POST | `/repo/import-hpkr` | importa un repo Haiku di terze parti (admin) |
| GET  | `/repo/{vendor}/{arch}/current/repo.info` | HaikuDepot |
| GET  | `/repo/{vendor}/{arch}/current/repo` | HaikuDepot (catalogo HPKR) |
| GET  | `/repo/{vendor}/{arch}/current/packages/{file}` | HaikuDepot (hpkg) |

## Prossimi passi (non in v1)

1. **Demone Haiku** che consuma `/library/pending` — chiude il cerchio Play Store.
2. **Crawler GitHub release** per i canali `ombra` (github-latest + pattern match).
3. **Tier di fiducia, firma manifest, transparency log** — fuori dal cichéto,
   asserzioni firmate dell'indice.
4. **Parte commerciale** (`spritz offri`, app a pagamento via Merchant of Record).
5. Magic-link opzionale, refresh token, store rate-limit su Redis in prod.

Da verificare su Haiku reale (non in WSL): rendering del frontend in WebPositive,
il probe del client nativo e lo schema `spritz://`, e l'aggiunta del repo-proxy
in HaikuDepot.

## Note di sicurezza

- **`/ingest` è admin-only** (`X-Admin-Token`); chiuso se il token non è
  configurato. La chiave JWT e il token admin vengono dall'ambiente, e in
  `prod` l'app rifiuta di partire senza (vedi Variabili d'ambiente).
- **Auth**: password min 8 caratteri, JWT a vita breve (2h) con revoca via
  `token_version` (`logout-all`, cambio password). Login con 401 generico (non
  rivela se l'email esiste). Rate-limit su login/register/ingest.
- **Ingest**: URL git validato (https; locale solo in dev), clone con timeout e
  cap su dimensione e numero file.
- **Repo-proxy**: SSRF guard sugli URL autore (in prod solo https, no indirizzi
  interni/loopback), download con cap di dimensione, sha256 sempre verificato.
- `sha256` obbligatorio sui canali pinned; verificato dal demone al download.
- I canali `github-latest` non pre-calcolano l'hash: il demone verifica al volo
  e logga l'hash visto (trade-off accettabile per i soli nightly).
- Trust tier e prezzo **non** stanno nel cichéto (file editabile nel repo git):
  vanno nell'indice firmato, così un fork non si auto-promuove.
