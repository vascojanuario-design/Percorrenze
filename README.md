# Portale percorsi

Portale interno per correggere le gite di raccolta in modo condiviso. Ogni correzione viene salvata sul server come nuova versione, con autore, data e nota. Nessuna versione viene mai sovrascritta.

## Accessi e ruoli

Si entra con nome utente e password. Le password sono salvate solo in forma cifrata, nel repository dei dati.

| Ruolo | Cosa può fare |
| --- | --- |
| Amministratore | Tutto: utenti, cantieri, mezzi e gite di ogni cantiere |
| Responsabile di cantiere | Corregge le gite e gestisce mezzi e assegnazioni dei suoi cantieri |
| Operatore | Vede le gite dei suoi cantieri e scarica il GPX da aprire in OsmAnd |

Il **primo amministratore** si definisce nei Secrets dell'app, e resta sempre valido come accesso di emergenza:

```toml
[amministratore]
utente = "admin"
password = "una-password-lunga-e-solo-tua"
nome = "Amministratore"
```

Gli altri utenti si creano dalla scheda **Utenti**. Ognuno può cambiare la propria password dalla barra laterale. Ricaricando la pagina del browser bisogna rientrare.

## Cantieri, mezzi e gite

Ogni gita appartiene a un cantiere e a un mezzo; un mezzo può avere più gite (gita 1, 2, 3…), ognuna con turno e giorni. Si gestisce tutto dalla scheda **Flotta**, scegliendo il cantiere nella barra laterale. Le gite importate senza cantiere compaiono all'amministratore sotto "Senza cantiere", da dove si assegnano.

## Struttura del portale

Il cantiere si sceglie una volta sola nella barra laterale e vale per tutte le pagine. Il menu ha tre sezioni:

- **Home**: numeri del cantiere (gite, chilometri, progetti, segnalazioni da verificare), avvisi (archivio non permanente, token in scadenza, rimessa mancante), pulsanti rapidi, anteprime delle gite e attività recente.
- **Gite**: Elenco gite, Editor, Nuove gite, Percorrenze.
- **Organizzazione**: Cantieri e mezzi, Utenti (solo amministratore), Impostazioni.

Ogni pagina ha un suo indirizzo (per esempio `/gite`, `/editor`), che si può salvare nei preferiti.

## Elenco gite

Nella pagina **Elenco gite** si cercano le gite per nome, si filtrano per stato (attive, progetti in corso, cestino) e si caricano nuovi GPX. Selezionando una gita si apre la sua **scheda**: anteprima, dati, e i pulsanti **Modifica** (apre l'editor, o l'area di progettazione per un progetto, con la gita già selezionata), **Rinomina**, **Naviga**, **GPX**, **Cestino** / **Ripristina**; sotto, le **versioni** (scarica, ripristina, fissa per gli operatori) e l'**attività**. Selezionando più gite si agisce su tutte insieme.

Si vedono tutte le gite con il loro stato: attiva (eventualmente con la versione fissata per gli operatori), progetto in corso, nel cestino. Si selezionano con la casella a sinistra e si può: spostarle nel cestino, ripristinarle, scaricarne i GPX in uno zip. L'**eliminazione definitiva** (della gita e di tutte le sue versioni) è riservata all'amministratore e vale solo per le gite già nel cestino.

## Creare gite senza GPX (scheda "Nuove gite")

Nella scheda **Nuove gite** si sceglie il cantiere e si apre l'**area di progettazione in una nuova finestra** del browser, già collegata con il proprio utente (con un link monouso valido 10 minuti). Se il browser blocca le nuove finestre, **Apri qui** la apre nella stessa pagina. Nell'area di progettazione:

1. scegli in alto cantiere e, se lo sai già, il mezzo;
2. **+ Nuovo progetto**, scrivi il nome e disegna cliccando sulla mappa (barra degli strumenti sopra la mappa: Disegna, Punto d'interesse, Annulla, Ripeti, Inquadra);
3. aggiungi i punti d'interesse;
4. **Salva bozza** per salvare sul server e riprendere quando vuoi, **Concludi la gita** quando è finita.

I progetti in corso sono gite con stato "bozza": stanno sul server, li vedono i colleghi del cantiere, ma non compaiono nell'editor delle gite, nello storico né agli operatori. Concludendo, la gita passa tra quelle del cantiere e gli operatori la vedono subito.

## Punti d'interesse e note

Nell'editor, sezione **Percorso e punti d'interesse**:

- Con **Disegna percorso** si allunga una gita esistente; se è selezionato un punto, i nuovi vengono inseriti subito dopo. **Esc** termina, **Annulla** toglie l'ultimo punto.
- **Aggiungi punto o nota**: clic sulla mappa, poi scegli il tipo (cassonetti, utenza critica, attenzione, accesso, nota) e scrivi il testo. I punti si trascinano e si eliminano come quelli del percorso.

Punti e note vengono salvati nel GPX della gita come waypoint, insieme al percorso e con lo stesso storico delle versioni. OsmAnd li mostra sulla mappa quando l'operatore apre il giro.

## Navigazione per gli operatori

L'operatore entra dal telefono, vede **tutte le gite attive** del suo cantiere (con ricerca per nome) e preme **Avvia navigazione**. Anche l'ufficio ha la stessa vista nella scheda **Percorrenze**. La guida si apre a tutto schermo:

- indicazione della prossima svolta, anche a voce ("Gira a destra tra 80 metri", "Inversione a U");
- tratti già percorsi in verde, prossimi 300 metri in arancione, percentuale di avanzamento;
- avviso quando si esce dal percorso e riquadro (con vibrazione) all'arrivo a un punto d'interesse;
- segue la **sequenza** della gita, quindi regge i ripassi sulla stessa strada;
- schermo sempre acceso; se la pagina si chiude, la navigazione riprende dal punto raggiunto (stesso giorno);
- a fine giro, riepilogo con percentuale e tratti non percorsi, evidenziabili in rosso sulla mappa.

**Privacy:** la posizione resta sul telefono. Nulla viene inviato al server: per questo non è un controllo a distanza. Inviare all'ufficio percentuali o tratti saltati richiederebbe prima l'accordo sindacale o l'autorizzazione dell'Ispettorato (art. 4 Statuto dei Lavoratori) e la valutazione d'impatto GDPR.

Dall'ufficio, nella scheda Storico versioni, **Prova la navigazione** apre la stessa guida; con **Prova senza GPS** la gita scorre da sola (utile anche come ripasso per i sostituti). Il pulsante **GPX** resta disponibile per chi preferisce un'altra app, come OsmAnd.

## Versione usata dagli operatori

Gli operatori vedono sempre l'**ultima versione** di ogni gita attiva del cantiere. Se serve rifare una gita senza disturbare chi è in strada, dalla scheda Storico versioni si può **fissare una versione per gli operatori**: continueranno a usare quella finché non si sceglie **Usa sempre l'ultima versione**.

Per ora l'operatore vede tutte le gite attive del cantiere, senza legame con il mezzo (il mezzo abituale nella scheda Utenti resta disponibile per sviluppi futuri).

## Come funziona per chi lo usa

1. Si entra con il proprio utente e si sceglie il cantiere nella barra laterale.
2. Nella scheda **Editor** si sceglie una gita e la si corregge. Le modifiche restano una bozza su quel computer, anche chiudendo il browser.
3. Si scrive cosa si è corretto e si preme **Invia**. Da quel momento la nuova versione è visibile a tutti.
4. Nella scheda **Storico versioni** si vedono tutte le versioni, si scarica il GPX di ognuna e si può rimettere attuale una versione precedente.

Se due persone correggono la stessa gita, vince chi invia per primo. Il secondo non perde il lavoro: la sua bozza resta nell'editor come copia "(tua bozza)", da confrontare con la nuova versione.

Le nuove gite si caricano dalla barra laterale (**Aggiungi gite**). Al primo avvio vengono importate in automatico le gite della cartella `seed/`.

## Struttura del progetto

```
app.py              pagina Streamlit
archivio.py         lettura e scrittura di gite e versioni (disco o GitHub)
anagrafica.py       utenti, ruoli, password cifrate, cantieri e mezzi
editor/index.html   editor della mappa (componente Streamlit)
seed/               gite importate al primo avvio, se l'archivio è vuoto
.streamlit/         configurazione di Streamlit
deploy/             esempi per systemd e nginx
```

## Dove finiscono i dati

Le gite possono stare in due posti, con la stessa identica struttura:

```
gite/<id-gita>/meta.json   nome, storico versioni, autori
gite/<id-gita>/v001.gpx    una versione per file, in GPX standard
anagrafica/utenti.json     utenti e password cifrate
anagrafica/flotte.json     cantieri e mezzi
```

- **Repository GitHub privato**, per usare il portale online (Streamlit Community Cloud) durante lo sviluppo. Ogni correzione inviata diventa un commit con autore e nota.
- **Cartella sul server**, per l'uso definitivo in azienda. È la scelta predefinita quando non c'è nessuna configurazione: la cartella è quella indicata da `PERCORSI_DATA_DIR` (predefinita `./dati`).

## Uso online con Streamlit Community Cloud

Su Community Cloud il disco si azzera a ogni riavvio, quindi le gite vanno salvate in un repository GitHub separato da quello del codice.

1. **Crea il repository dei dati.** Su GitHub: New repository, nome per esempio `percorrenza-dati`, visibilità **Private**, spunta "Add a README file" (il repository non deve essere vuoto).
2. **Crea un token di accesso limitato a quel repository.** Su GitHub: foto profilo, Settings, Developer settings, Personal access tokens, **Fine-grained tokens**, Generate new token.
   - Repository access: *Only select repositories*, scegli `percorrenza-dati`.
   - Permissions, Repository permissions: **Contents: Read and write**.
   - Scegli una scadenza (per esempio un anno) e annotala: alla scadenza l'app smette di salvare finché non metti un token nuovo.
   - Copia il token: GitHub lo mostra una sola volta.
3. **Inserisci la configurazione nell'app.** Su share.streamlit.io apri l'app, Settings, **Secrets**, e incolla:

   ```toml
   [archivio]
   tipo = "github"
   repo = "tuo-utente/percorrenza-dati"
   branch = "main"
   token = "github_pat_..."

   [amministratore]
   utente = "admin"
   password = "una-password-lunga-e-solo-tua"
   nome = "Amministratore"
   ```

4. Salva: l'app si riavvia, importa le gite della cartella `seed/` nel repository dei dati e nella barra laterale mostra "Archivio: GitHub …".

Il token non va mai scritto nei file del repository del codice: sta solo nei Secrets. Conviene rendere privato anche il repository del codice, perché la cartella `seed/` contiene i percorsi.

## Passaggio al server aziendale

Sul server basta copiare il repository dei dati nella cartella dati e non configurare nessun secret:

```bash
git clone https://github.com/tuo-utente/percorrenza-dati.git /srv/percorsi/dati
```

Da quel momento l'app salva su disco, con tutto lo storico delle versioni fatte online. In alternativa il server può continuare a usare GitHub: in quel caso la stessa configurazione dei Secrets va in `.streamlit/secrets.toml` sul server.

Per il backup della cartella basta copiarla. I GPX si aprono con qualsiasi programma.

## Prova sul proprio computer

Serve Python 3.10 o successivo.

```bash
python -m venv .venv
source .venv/bin/activate        # su Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Si apre su http://localhost:8501.

## Installazione sul server (Linux)

```bash
sudo useradd --system --home /opt/percorsi percorsi
sudo mkdir -p /opt/percorsi /srv/percorsi/dati
sudo cp -r . /opt/percorsi
sudo chown -R percorsi: /opt/percorsi /srv/percorsi
cd /opt/percorsi
sudo -u percorsi python3 -m venv .venv
sudo -u percorsi .venv/bin/pip install -r requirements.txt

sudo cp deploy/percorsi.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now percorsi
```

Il servizio ascolta solo su `127.0.0.1:8501`: per raggiungerlo dalla rete aziendale va messo dietro nginx (prossima sezione).

### Accesso protetto con nginx

Il file `deploy/nginx-percorsi.conf` è un esempio pronto con HTTPS e password. Due righe sono importanti:

- le intestazioni `Upgrade` e `Connection`: Streamlit usa i websocket e senza di esse la pagina resta bianca;
- `X-Remote-User`: passa all'app il nome con cui la persona ha fatto login, che diventa automaticamente l'autore delle versioni.

Se l'azienda ha già un login centralizzato (Active Directory, Microsoft Entra, Keycloak), l'IT può usarlo al posto delle password di nginx, purché passi il nome utente nella stessa intestazione. Il nome dell'intestazione si cambia con la variabile `PERCORSI_HEADER_UTENTE`.

### In alternativa, con Docker

```bash
docker compose up -d --build
```

I dati restano nella cartella `./dati` accanto al progetto.

## Cose da sapere

- **Mappe di sfondo.** Sono caricate da servizi esterni (Esri e OpenStreetMap). Vanno bene per una fase pilota con pochi utenti. Per l'uso a regime conviene un fornitore con contratto o un server di mappe interno.
- **Bozze.** Restano nel browser di chi le fa. Se si cambia computer, le bozze non inviate non lo seguono.
- **Più utenti insieme.** Su disco l'archivio usa un lock su file; su GitHub ogni salvataggio controlla che nessuno abbia scritto nel frattempo. In entrambi i casi una versione non può sovrascriverne un'altra. Non avviare più server sulla stessa cartella condivisa via rete.
- **Prossimi passi previsti.** Aggancio automatico alle strade con un motore di routing (Valhalla), punti di raccolta, collegamento con il modulo di gestione e database PostGIS.
