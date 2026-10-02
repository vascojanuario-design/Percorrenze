# Percorrenza – contesto del progetto

Portale per gestire i percorsi (gite) dei servizi di igiene urbana: correzione condivisa delle gite in GPX, poi distribuzione agli operatori sui mezzi, infine verifica della percentuale di percorrenza.

Lingua: interfaccia, messaggi, commenti e nomi nel codice sono in **italiano**. Rispondi all'utente in italiano.

## Obiettivo e fasi

1. **Mappatura e portale (in corso).** Caricare e correggere le gite, con storico versioni.
2. **App per gli operatori.** Ricevere sul telefono la gita aggiornata e seguirla, per ridurre i giorni di affiancamento.
3. **Verifica.** Confrontare le tracce GPS reali con il percorso e calcolare la percentuale percorsa, tratto per tratto.

## Struttura del repository

```
app.py              pagina Streamlit: accesso, barra laterale (cantiere, mezzo), schede Editor, Storico, Flotta, Utenti; pagina semplice per gli operatori
archivio.py         GPX (lettura, pulizia, scrittura), archivio versioni su disco o su GitHub, documenti di anagrafica
anagrafica.py       utenti, ruoli, password cifrate (pbkdf2), cantieri, mezzi, giorni e turni
editor/index.html   editor della mappa: componente Streamlit bidirezionale, file unico, nessun build
seed/               gite importate al primo avvio se l'archivio è vuoto
deploy/             esempi systemd e nginx per il server aziendale
Dockerfile, docker-compose.yml, requirements.txt, README.md
.streamlit/config.toml   (vedi in fondo: va creato se manca)
```

## Come funziona

### Archivio (`archivio.py`)
- Layout dati, identico su disco e su GitHub: `gite/<id>/meta.json` + `gite/<id>/vNNN.gpx`.
- Una versione per file, **mai sovrascritta**. Ripristinare una versione vecchia crea una versione nuova.
- `meta.json`: `id`, `nome`, `creata`, `creata_da`, `archiviata`, `versioni[]` (`n`, `file`, `data`, `autore`, `nota`, `nome`, `punti`, `km_tot`, `km_raccolta`, `km_trasferimento`, `invio`), `eventi[]`.
- Due depositi intercambiabili, scelti dalla sezione `[archivio]` dei secrets di Streamlit:
  - `DepositoLocale`: cartella `PERCORSI_DATA_DIR` (predefinita `./dati`), lock su file, scritture atomiche, `meta.json` scritto per ultimo.
  - `DepositoGitHub`: repository privato dei dati (`percorrenza-dati`), ogni salvataggio è un commit unico via Git Data API; aggiornamento del branch non forzato, quindi una scrittura concorrente viene rifiutata e non sovrascrive.
- Senza secrets si usa il disco.
- `salva(..., base=N)` solleva `Conflitto` se la versione attuale non è più `N`.

### Accessi, cantieri e mezzi
- Ruoli: `amministratore` (tutto), `responsabile` (gite, mezzi e assegnazioni dei propri cantieri), `operatore` (vede e scarica le gite dei propri cantieri).
- Primo amministratore nei secrets, sezione `[amministratore]` (`utente`, `password`, `nome`): sempre valido, è l'accesso di emergenza.
- `anagrafica/utenti.json`: utenti con password cifrata, ruolo, cantieri, attivo. Mai password in chiaro.
- `anagrafica/flotte.json`: `cantieri` {id: nome, rimessa [lat, lon]} e `mezzi` {id: codice, targa, tipo, cantiere, attivo}.
- Ogni gita ha in `meta.json` i campi `cantiere`, `mezzo`, `numero`, `turno`, `giorni`. Si cambiano con `Archivio.assegna()`, che non crea una nuova versione del percorso ma registra un evento.
- Un mezzo può avere più gite; una gita ha un solo mezzo.
- Ogni azione dell'editor verifica i permessi lato server (`puo_modificare`).
- Le tabelle della scheda Flotta usano `st.data_editor`; la chiave cambia dopo ogni salvataggio (`chiave()`), così ripartono dai dati salvati.
- La sessione vive in `st.session_state`: ricaricando la pagina si rientra.

### Punti e tratti
- Un punto è `[lat, lon, tipo]`, con tipo `"r"` (raccolta) o `"t"` (trasferimento).
- Il tipo di un segmento `i → i+1` è quello del punto `i`.
- Nel GPX ogni tratto omogeneo è un `trkseg` con `<extensions><p:tipo>raccolta|trasferimento</p:tipo></extensions>`, namespace `urn:percorsi:1`.
- `pulisci()` toglie i punti doppi consecutivi (< 0,5 m) e conserva il tipo del tratto successivo.

### Editor (`editor/index.html`)
- Leaflet 1.9.4 da cdnjs. Sfondi: Stradale (Esri World_Street_Map), OpenStreetMap, Satellite e Satellite con vie (Esri). CARTO non si usa: richiede una chiave a pagamento. Niente build: resta un file unico.
- Protocollo con Streamlit senza libreria: all'avvio invia `streamlit:componentReady`, riceve `streamlit:render` con gli argomenti `data`, `data_version`, `user`, `msg`, `height`, risponde con `streamlit:setComponentValue`.
- Azioni inviate a Python: `save`, `create`, `archive`. Ognuna ha un `nonce`; Python lo salva nel campo `invio` della versione, così l'editor riconosce i propri salvataggi.
- Bozze nel `localStorage` del browser: `percorsi-bozza-<id>` (bozza legata alla versione `base`), `percorsi-chiuse-<id>` (segnalazioni chiuse), `percorsi-locali` (gite non ancora sul server).
- Se un collega salva prima, la bozza non viene persa: diventa una gita locale "(tua bozza)".
- Segnalazioni automatiche: segmenti oltre 250 m (soglia regolabile), andata e ritorno sotto i 30 m (probabile clic sbagliato), inversioni a U (coseno < -0,9).
- Modalità "Segui": evidenzia i prossimi 300 m nella sequenza. È la base della futura guida per gli operatori.

## Caratteristiche delle gite reali

- Disegnate con gpx.studio: una sola traccia, nessun orario, nessun waypoint.
- Zona Campi Bisenzio / San Donnino. Sette gite da 15 a 36 km.
- Tra il 58% e l'86% della lunghezza di ogni gita passa su strade già percorse nella stessa gita, con fino a 29 inversioni a U. Per questo la guida deve seguire la **sequenza**, non agganciarsi al tratto più vicino.
- Alcune gite condividono molte strade (gita 1 camion con gita 4: 47%; con gita porter: 41%).

## Dove gira

- **Adesso:** Streamlit Community Cloud, dati nel repository GitHub privato `percorrenza-dati`, token nei Secrets dell'app.
- **Alla fine:** server aziendale. Si clona `percorrenza-dati` nella cartella dati e si usa il deposito su disco. Dettagli nel README.

## Regole

- Non scrivere mai token, password o secrets nei file del repository. `.streamlit/secrets.toml` è in `.gitignore`.
- Non cambiare il formato di `meta.json` o dei GPX senza mantenere la lettura dei dati già esistenti.
- Mai sovrascrivere o cancellare versioni.
- Prima di consegnare una modifica, prova l'app: `PERCORSI_DATA_DIR=/tmp/prova streamlit run app.py`, poi controlla editor, invio e storico.
- Le modifiche al codice su `main` fanno ripartire l'app su Community Cloud: lavora su un branch e proponi una pull request.

## Prossimi passi, in ordine

Fatto: accessi con ruoli, cantieri, mezzi, assegnazione delle gite (mezzo, numero, turno, giorni), pagina semplice per gli operatori.

1. **Stato "pubblicata".** Non ogni versione inviata deve arrivare sul mezzo. Serve un'approvazione esplicita (responsabile o amministratore): per ogni gita si ricorda la versione pubblicata, chi l'ha approvata e quando. La pagina operatori deve poi mostrare solo la versione pubblicata.
2. **Pagina per i mezzi, pensata per il telefono.** Partire dalla scheda operatore esistente: gite del giorno per mezzo e turno, pulsante grande per aprire in OsmAnd, QR stampabile per ogni mezzo.
3. **Pilota con OsmAnd** su due o tre gite: verificare se la navigazione lungo la traccia regge i ripassi.
4. **Guida propria (web app installabile)**, se il pilota mostra che serve: mappa offline, schermo sempre acceso, logica "Segui".
5. **App nativa e registrazione delle tracce** per la fase di verifica.

Più avanti: aggancio automatico alle strade (Valhalla, profilo camion), punti di raccolta lungo il percorso, collegamento con il modulo di gestione esistente, database PostGIS.

**Attenzione legale:** finché l'app guida soltanto, senza registrare né inviare la posizione, non c'è controllo a distanza. Prima di registrare o trasmettere posizioni degli operatori servono l'accordo sindacale o l'autorizzazione dell'Ispettorato (art. 4 Statuto dei Lavoratori) e la valutazione d'impatto GDPR (DPIA). Non implementare tracciamento senza conferma esplicita dell'utente su questo punto.

## Domande ancora aperte

- Telefoni degli operatori: personali, aziendali o tablet sul mezzo? Android o iPhone?
- Nei nomi delle gite, "35" è il numero del mezzo (probabile: ogni mezzo ha le sue gite numerate).
- Regola di nomenclatura delle gite (proposta: zona, mezzo, turno, numero gita).
- La gita 1 camion è una versione superata o un servizio diverso sulle stesse strade?

## `.streamlit/config.toml`

Se manca nel repository, crealo con questo contenuto:

```toml
[server]
headless = true
maxUploadSize = 20
enableXsrfProtection = true

[browser]
gatherUsageStats = false

[theme]
primaryColor = "#1C2A2E"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F1F4F3"
textColor = "#1C2A2E"

[client]
toolbarMode = "viewer"
```
