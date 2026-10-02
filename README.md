# Portale percorsi

Portale interno per correggere le gite di raccolta in modo condiviso. Ogni correzione viene salvata sul server come nuova versione, con autore, data e nota. Nessuna versione viene mai sovrascritta.

## Come funziona per chi lo usa

1. Si scrive il proprio nome nella barra laterale (non serve se l'accesso passa dal proxy con login, vedi sotto).
2. Nella scheda **Editor** si sceglie una gita e la si corregge. Le modifiche restano una bozza su quel computer, anche chiudendo il browser.
3. Si scrive cosa si è corretto e si preme **Invia**. Da quel momento la nuova versione è visibile a tutti.
4. Nella scheda **Storico versioni** si vedono tutte le versioni, si scarica il GPX di ognuna e si può rimettere attuale una versione precedente.

Se due persone correggono la stessa gita, vince chi invia per primo. Il secondo non perde il lavoro: la sua bozza resta nell'editor come copia "(tua bozza)", da confrontare con la nuova versione.

Le nuove gite si caricano dalla barra laterale (**Aggiungi gite**). Al primo avvio vengono importate in automatico le gite della cartella `seed/`.

## Struttura del progetto

```
app.py              pagina Streamlit
archivio.py         lettura e scrittura di gite e versioni su disco
editor/index.html   editor della mappa (componente Streamlit)
seed/               gite importate al primo avvio, se l'archivio è vuoto
.streamlit/         configurazione di Streamlit
deploy/             esempi per systemd e nginx
```

I dati stanno nella cartella indicata da `PERCORSI_DATA_DIR` (predefinita: `./dati`):

```
dati/gite/<id-gita>/meta.json   nome, storico versioni, autori
dati/gite/<id-gita>/v001.gpx    una versione per file, in GPX standard
```

Per il backup basta copiare la cartella `dati`. I GPX si aprono con qualsiasi programma.

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

- **Mappe di sfondo.** Sono caricate da servizi esterni (CARTO, OpenStreetMap, Esri satellite). Vanno bene per una fase pilota con pochi utenti. Per l'uso a regime conviene un fornitore con contratto o un server di mappe interno.
- **Bozze.** Restano nel browser di chi le fa. Se si cambia computer, le bozze non inviate non lo seguono.
- **Un solo processo.** L'archivio usa un lock su file, quindi funziona correttamente con più utenti sullo stesso server. Non va avviato su più server che condividono la stessa cartella via rete.
- **Prossimi passi previsti.** Aggancio automatico alle strade con un motore di routing (Valhalla), punti di raccolta, collegamento con il modulo di gestione e database PostGIS.
