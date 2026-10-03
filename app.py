"""Portale percorsi: correzione condivisa delle gite di raccolta, organizzate per cantiere e mezzo.

Avvio:  streamlit run app.py
Configurazione nei secrets (vedi README): [archivio] per dove salvare, [amministratore] per il primo accesso.
"""
import os
import secrets as segreto
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import anagrafica as an
from archivio import Conflitto, ErroreArchivio, apri, leggi_gpx, leggi_waypoint, pulisci

BASE = Path(__file__).parent
DATA_DIR = Path(os.environ.get("PERCORSI_DATA_DIR", BASE / "dati"))
HEADER_UTENTE = os.environ.get("PERCORSI_HEADER_UTENTE", "X-Remote-User")
ALTEZZA_EDITOR = 820
TUTTI, SENZA = "*", "-"

LOGO = BASE / "assets" / "logo.png"
ICONA = BASE / "assets" / "icona.png"

st.set_page_config(page_title="Percorsi · Cristoforo", page_icon=str(ICONA) if ICONA.exists() else "🗺️", layout="wide")
st.markdown("""<style>
:root{--verde:#009640;--verde-scuro:#007A34;--verde-chiaro:#E8F5EC;--inchiostro:#16301F}
.block-container{padding-top:3.2rem;padding-bottom:1rem;max-width:100%}
[data-testid="stBaseButton-primary"],[data-testid="stBaseButton-primaryFormSubmit"]{background:var(--verde)!important;border-color:var(--verde)!important;color:#fff!important}
[data-testid="stBaseButton-primary"]:hover,[data-testid="stBaseButton-primaryFormSubmit"]:hover{background:var(--verde-scuro)!important;border-color:var(--verde-scuro)!important}
[data-baseweb="tab-highlight"]{background-color:var(--verde)!important}
.stTabs [aria-selected="true"] p{color:var(--verde)!important;font-weight:600}
[data-testid="stMetricValue"]{color:var(--verde)}
.titolo-pagina{display:flex;flex-direction:column;margin:0 0 2px;line-height:1.25}
.titolo-pagina b{font-size:1.45rem;white-space:nowrap}
.titolo-pagina span{opacity:.7;font-size:.9rem}
</style>""", unsafe_allow_html=True)
if LOGO.exists():
    try:
        st.logo(str(LOGO), icon_image=str(ICONA) if ICONA.exists() else None, size="large")
    except TypeError:
        st.logo(str(LOGO))

editor = components.declare_component("editor_percorsi", path=str(BASE / "editor"))
guida = components.declare_component("guida_percorsi", path=str(BASE / "guida"))


def segreti(sezione: str) -> dict:
    try:
        return dict(st.secrets[sezione])
    except Exception:
        return {}


@st.cache_resource(show_spinner="Apertura archivio…")
def apri_archivio():
    a = apri(segreti("archivio"), DATA_DIR)
    a.semina(BASE / "seed")
    return a


try:
    archivio = apri_archivio()
except ErroreArchivio as e:
    st.error(f"Archivio non disponibile. {e}")
    st.caption("Controlla la sezione [archivio] nei secrets dell'app (vedi README).")
    st.stop()

ADMIN = segreti("amministratore")


def data_breve(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")


def avviso(testo: str, ok: bool = True, nonce: str | None = None, local_id: str | None = None,
           gita_id: str | None = None) -> None:
    """Messaggio mostrato sia da Streamlit sia dentro l'editor."""
    st.session_state.msg = {"nonce": nonce or str(datetime.now().timestamp()), "ok": ok, "text": testo,
                            "local_id": local_id, "gita_id": gita_id}
    st.session_state.avvisi = st.session_state.get("avvisi", []) + [(testo, ok)]


def vuoto(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip())


def righe(df: pd.DataFrame) -> list[dict]:
    return [{k: (None if vuoto(v) else v) for k, v in r.items()} for r in df.to_dict("records")]


# ================================================================ accesso

utenti_doc = archivio.leggi_doc("utenti", an.UTENTI_VUOTO)


@st.cache_resource
def gettoni() -> dict:
    """Gettoni monouso (10 minuti) per aprire l'area di progettazione in un'altra finestra già collegati."""
    return {}


def nuovo_gettone(chi: dict) -> str:
    adesso = time.time()
    for k in [k for k, (scad, _) in gettoni().items() if scad < adesso]:
        gettoni().pop(k, None)
    t = segreto.token_urlsafe(24)
    gettoni()[t] = (adesso + 600, dict(chi))
    return t


qp = st.query_params
if qp.get("t"):
    voce = gettoni().pop(qp.get("t"), None)
    if voce and voce[0] > time.time() and "chi" not in st.session_state:
        st.session_state.chi = voce[1]
    if qp.get("area") == "crea":
        st.session_state.pagina = "crea"
        st.session_state.finestra_separata = True
        if qp.get("c"):
            st.session_state.crea_cantiere_iniziale = qp.get("c")
    st.query_params.clear()

if "chi" not in st.session_state:
    dal_proxy = st.context.headers.get(HEADER_UTENTE)
    u = utenti_doc["utenti"].get((dal_proxy or "").lower())
    if dal_proxy and u and u.get("attivo", True):
        st.session_state.chi = an.sessione(dal_proxy.lower(), u)

if "chi" not in st.session_state:
    _, centro, _ = st.columns([1, 1.2, 1])
    with centro:
        st.write("")
        if LOGO.exists():
            st.image(str(LOGO), width="stretch")
        st.subheader("Percorsi di raccolta")
        st.write("Accedi con il nome utente e la password che ti ha dato l'amministratore.")
        if not ADMIN and not utenti_doc["utenti"]:
            st.warning("Nessun utente configurato. Aggiungi la sezione [amministratore] nei secrets dell'app "
                       "per creare il primo accesso (vedi README).")
        with st.form("accesso"):
            nome_utente = st.text_input("Nome utente", autocomplete="username")
            password = st.text_input("Password", type="password", autocomplete="current-password")
            if st.form_submit_button("Entra", type="primary", width="stretch"):
                chi = an.accedi(utenti_doc, ADMIN, nome_utente, password)
                if chi:
                    st.session_state.chi = chi
                    st.rerun()
                time.sleep(1.5)
                st.error("Nome utente o password non corretti.")
    st.stop()

chi = an.rinfresca(utenti_doc, st.session_state.chi)
if chi is None:
    st.session_state.clear()
    st.warning("Il tuo accesso è stato disattivato. Rivolgiti all'amministratore.")
    st.stop()
st.session_state.chi = chi
ruolo = chi["ruolo"]
amministratore = ruolo == "amministratore"
utente = chi["nome"]

flotte = archivio.leggi_doc("flotte", an.FLOTTE_VUOTO)
miei_cantieri = an.cantieri_visibili(flotte, chi)


def nome_cantiere(cid: str | None) -> str:
    if cid == TUTTI:
        return "Tutti i cantieri"
    if cid in (SENZA, None):
        return "Senza cantiere"
    return flotte["cantieri"].get(cid, {}).get("nome", "Cantiere eliminato")


def puo_modificare(m: dict) -> bool:
    return amministratore or (ruolo == "responsabile" and m.get("cantiere") in chi["cantieri"])


# ================================================================ barra laterale

with st.sidebar:
    st.caption(chi["nome"] if chi["nome"].lower() == an.RUOLI[ruolo].lower() else f"{chi['nome']}, {an.RUOLI[ruolo].lower()}")

    opzioni = ([TUTTI] if amministratore else []) + miei_cantieri + ([SENZA] if amministratore else [])
    if not opzioni:
        st.info("Non hai ancora un cantiere assegnato. Chiedi all'amministratore di associarti a un cantiere.")
        cantiere_sel = None
    else:
        cantiere_sel = st.selectbox("Cantiere", opzioni, format_func=nome_cantiere, key="cantiere_sel")

    mezzo_sel = TUTTI
    if cantiere_sel and cantiere_sel not in (TUTTI, SENZA) and ruolo != "operatore":
        mezzi_opz = [TUTTI] + an.mezzi_del_cantiere(flotte, cantiere_sel) + [SENZA]
        mezzo_sel = st.selectbox("Mezzo", mezzi_opz, key=f"mezzo_sel_{cantiere_sel}",
                                 format_func=lambda m: "Tutti i mezzi" if m == TUTTI else an.etichetta_mezzo(flotte, m))

    if ruolo != "operatore" and cantiere_sel:
        st.divider()
        st.subheader("Carica gite da GPX")
        dest = cantiere_sel if cantiere_sel not in (TUTTI, SENZA) else None
        st.caption(f"Le gite caricate andranno in: {nome_cantiere(dest)}"
                   + (f", mezzo {an.etichetta_mezzo(flotte, mezzo_sel)}" if mezzo_sel not in (TUTTI, SENZA) else ""))
        chiave_upload = f"upload_{st.session_state.get('upload_n', 0)}"
        nuovi = st.file_uploader("File GPX", type=["gpx"], accept_multiple_files=True, key=chiave_upload,
                                 label_visibility="collapsed")
        if nuovi and st.button("Importa", type="primary", width="stretch"):
            for f in nuovi:
                try:
                    nome, pts = leggi_gpx(f.getvalue(), f.name)
                    pts, rimossi = pulisci(pts)
                    archivio.crea(nome, pts, utente,
                                  f"Importata da {f.name}" + (f", rimossi {rimossi} punti doppi" if rimossi else ""),
                                  cantiere=dest, mezzo=mezzo_sel if mezzo_sel not in (TUTTI, SENZA) else None,
                                  waypoint=leggi_waypoint(f.getvalue()))
                    avviso(f"Importata: {nome}")
                except (ValueError, ErroreArchivio) as e:
                    avviso(str(e), ok=False)
            st.session_state.upload_n = st.session_state.get("upload_n", 0) + 1
            st.rerun()

    st.divider()
    if not chi.get("da_secrets"):
        with st.expander("Cambia password"):
            with st.form("cambio_pw", clear_on_submit=True):
                attuale = st.text_input("Password attuale", type="password")
                nuova = st.text_input("Nuova password", type="password", help="Almeno 8 caratteri")
                if st.form_submit_button("Cambia"):
                    try:
                        archivio.modifica_doc("utenti", an.UTENTI_VUOTO,
                                              lambda d: an.cambia_password(d, chi["utente"], attuale, nuova),
                                              f"{chi['utente']}: password cambiata", utente)
                        st.success("Password cambiata.")
                    except (ValueError, ErroreArchivio) as e:
                        st.error(str(e))
    if st.button("Esci", width="stretch"):
        st.session_state.clear()
        st.rerun()
    if amministratore:
        st.caption(f"Archivio: {archivio.descrizione}")

for testo, ok in st.session_state.pop("avvisi", []):
    st.toast(testo, icon="✅" if ok else "⚠️")

if not cantiere_sel:
    st.stop()


# ================================================================ gite del cantiere scelto

def nel_filtro(m: dict) -> bool:
    c = m.get("cantiere")
    if cantiere_sel == TUTTI:
        ok = True
    elif cantiere_sel == SENZA:
        ok = c is None or c not in flotte["cantieri"]
    else:
        ok = c == cantiere_sel
    if ok and mezzo_sel == SENZA:
        ok = not m.get("mezzo") or m.get("mezzo") not in flotte["mezzi"]
    elif ok and mezzo_sel != TUTTI:
        ok = m.get("mezzo") == mezzo_sel
    return ok


def ordine(m: dict):
    v = flotte["mezzi"].get(m.get("mezzo") or "", {})
    return (an._ordinabile(v.get("codice", "zzz")), m.get("numero") or 99, m["nome"].lower())


attive = sorted([m for m in archivio.elenco() if nel_filtro(m)], key=ordine)


@st.cache_data(show_spinner=False, max_entries=50)
def contenuto_versione(gid: str, versione: int) -> tuple[list, list]:
    return archivio.contenuto(gid, versione)


def scheda_editor():
    impronta = archivio.impronta()
    risposta = editor(data=dati_per_editor(attive), data_version=f"{impronta}|{cantiere_sel}|{mezzo_sel}", user=utente,
                      msg=st.session_state.get("msg"), height=ALTEZZA_EDITOR, key="editor", default=None)

    gestisci(risposta, cantiere_sel if cantiere_sel not in (TUTTI, SENZA) else None,
             mezzo_sel if mezzo_sel not in (TUTTI, SENZA) else None)


def gestisci(risposta, dest_cantiere: str | None, dest_mezzo: str | None) -> None:
    """Esegue sul server le azioni chieste dall'editor (salva, crea, concludi, archivia) e risponde all'editor."""
    if not risposta or risposta.get("nonce") == st.session_state.get("ultimo_nonce"):
        return
    st.session_state.ultimo_nonce = risposta["nonce"]
    azione, gid, nonce, stato = risposta.get("action"), risposta.get("gita_id"), risposta["nonce"], risposta.get("stato")
    nome = risposta.get("name") or "Gita senza nome"
    try:
        if azione in ("save", "archive") and not puo_modificare(archivio.meta(gid)):
            avviso("Non hai i permessi per modificare questa gita.", ok=False, nonce=nonce)
        elif azione == "save":
            testo = ""
            if not risposta.get("solo_stato"):
                n = archivio.salva(gid, risposta["pts"], utente,
                                   risposta.get("note") or ("Bozza" if stato == "bozza" else "Correzioni"),
                                   base=int(risposta["base"]), nome=nome, nonce=nonce, waypoint=risposta.get("wpts"))
                testo = f"Salvata la versione {n} di {nome}"
            if stato == "concludi":
                if dest_mezzo and not archivio.meta(gid).get("mezzo"):
                    archivio.assegna(gid, utente, mezzo=dest_mezzo)
                archivio.concludi(gid, utente)
                testo = f"Gita \"{nome}\" conclusa: la trovi nel portale, scheda Editor, pronta per essere pubblicata"
            avviso(testo or "Nessuna modifica", nonce=nonce)
        elif azione == "create":
            nuovo = archivio.crea(nome, risposta["pts"], utente,
                                  risposta.get("note") or ("Bozza" if stato == "bozza" else "Creata dall'editor"),
                                  nonce=nonce, cantiere=dest_cantiere, mezzo=dest_mezzo, waypoint=risposta.get("wpts"),
                                  stato="bozza" if stato == "bozza" else None)
            avviso(f"Progetto \"{nome}\" salvato sul server" if stato == "bozza" else
                   f"Gita \"{nome}\" creata" + (": la trovi nel portale, scheda Editor" if stato == "concludi" else ""),
                   nonce=nonce, local_id=risposta.get("local_id"), gita_id=nuovo if stato == "bozza" else None)
        elif azione == "archive":
            bozza = archivio.meta(gid).get("stato") == "bozza"
            archivio.archivia(gid, utente)
            avviso("Progetto eliminato. Resta recuperabile dallo storico delle gite archiviate." if bozza else
                   "Gita archiviata. Puoi riattivarla dallo storico.", nonce=nonce)
    except Conflitto as c:
        avviso(f"Non salvata: nel frattempo un collega ha inviato la versione {c.versione_attuale}. "
               "La tua bozza è conservata come copia \"(tua bozza)\": confrontala con la nuova versione "
               "e riporta lì le correzioni.", ok=False, nonce=nonce)
    except (ValueError, KeyError, FileNotFoundError, ErroreArchivio) as e:
        avviso(f"Non salvata: {e}", ok=False, nonce=nonce)
    st.rerun()


def dati_per_editor(gite: list[dict]) -> list[dict]:
    dati = []
    for m in gite:
        ultima = m["versioni"][-1]
        pts, wpts = contenuto_versione(m["id"], ultima["n"])
        dati.append({"id": m["id"], "name": m["nome"], "version": ultima["n"], "invio": ultima.get("invio"),
                     "pts": pts, "wpts": wpts})
    return dati


# ================================================================ crea gita (a tutto schermo)

def pagina_crea():
    st.markdown("<style>[data-testid='stSidebar'],[data-testid='stSidebarCollapsedControl'],"
                "[data-testid='stExpandSidebarButton']{display:none!important}"
                ".block-container{padding-top:2.4rem!important}</style>", unsafe_allow_html=True)
    testa = st.columns([3.2, 2, 2, 1.5], vertical_alignment="bottom")
    testa[0].markdown("<div class='titolo-pagina'><b>Area di progettazione</b>"
                      "<span>disegna il percorso e i punti d'interesse</span></div>", unsafe_allow_html=True)
    separata = st.session_state.get("finestra_separata")
    if testa[3].button("Vai al portale" if separata else "← Torna al portale", width="stretch",
                       help="Quando hai salvato puoi anche chiudere questa finestra" if separata else None):
        st.session_state.pagina = None
        st.session_state.finestra_separata = False
        st.rerun()
    iniziale = st.session_state.pop("crea_cantiere_iniziale", None)
    if iniziale in miei_cantieri:
        st.session_state.crea_cantiere = iniziale
    cant = testa[1].selectbox("Cantiere", miei_cantieri, format_func=nome_cantiere, key="crea_cantiere",
                              index=miei_cantieri.index(cantiere_sel) if cantiere_sel in miei_cantieri else 0)
    mezzi = [None] + an.mezzi_del_cantiere(flotte, cant, solo_attivi=True)
    mez = testa[2].selectbox("Mezzo", mezzi, key=f"crea_mezzo_{cant}",
                             format_func=lambda k: "Da decidere" if not k else an.etichetta_mezzo(flotte, k))
    bozze = sorted([m for m in archivio.elenco(bozze=True) if m.get("cantiere") == cant], key=lambda m: m["nome"].lower())
    risposta = editor(data=dati_per_editor(bozze), data_version=f"{archivio.impronta()}|crea|{cant}", user=utente,
                      msg=st.session_state.get("msg"), height=ALTEZZA_EDITOR, mode="crea", key="editor_crea", default=None)
    gestisci(risposta, cant, mez)


def descrizione_gita(m: dict) -> str:
    parti = [an.etichetta_mezzo(flotte, m.get("mezzo"))]
    if m.get("numero"):
        parti.append(f"gita {m['numero']}")
    if m.get("turno"):
        parti.append(m["turno"].lower())
    if m.get("giorni"):
        parti.append(an.scrivi_giorni(m["giorni"]))
    if cantiere_sel == TUTTI:
        parti.insert(0, nome_cantiere(m.get("cantiere")))
    return ", ".join(parti)


def scheda_storico():
    mostra_archiviate = st.toggle("Mostra le gite archiviate")
    gite = sorted([m for m in archivio.elenco(archiviate=mostra_archiviate) if nel_filtro(m)], key=ordine)
    if not gite:
        st.write("Nessuna gita archiviata qui." if mostra_archiviate else "Nessuna gita in questa selezione.")
        return
    st.download_button(f"Scarica le {len(gite)} gite di questa selezione (ZIP)", data=archivio.zip_ultime(gite),
                       file_name=f"gite_{datetime.now():%Y%m%d}.zip", mime="application/zip")
    m = st.selectbox("Gita", gite, format_func=lambda g: f"{g['nome']}  ({descrizione_gita(g)})")
    ultima = m["versioni"][-1]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Versione attuale", ultima["n"])
    c2.metric("Totale", f"{ultima['km_tot']:.1f} km".replace(".", ","))
    c3.metric("Raccolta", f"{ultima['km_raccolta']:.1f} km".replace(".", ","))
    c4.metric("Trasferimento", f"{ultima['km_trasferimento']:.1f} km".replace(".", ","))
    pub = m.get("pubblicata")
    if pub:
        testo = (f"Approvata per la strada: versione {pub['n']}, pubblicata da {pub['autore']} "
                 f"il {data_breve(pub['data'])}.")
        if pub["n"] != ultima["n"]:
            st.warning(testo + f" La versione {ultima['n']} non è ancora pubblicata: gli operatori vedono la {pub['n']}.")
        else:
            st.success(testo)
    else:
        st.info("Non ancora pubblicata: gli operatori non vedono questa gita.")
    st.dataframe(
        [{"Versione": v["n"], "Stato": "Pubblicata" if pub and pub["n"] == v["n"] else "",
          "Data": data_breve(v["data"]), "Autore": v["autore"], "Nota": v["nota"],
          "Km": v["km_tot"], "Punti": v["punti"], "Note sulla mappa": v.get("note_mappa", 0)}
         for v in reversed(m["versioni"])],
        hide_index=True, width="stretch",
    )
    col_v, col_dl, col_rip, col_pub = st.columns(4, vertical_alignment="bottom")
    n = col_v.selectbox("Versione", [v["n"] for v in reversed(m["versioni"])], key=f"ver_{m['id']}")
    col_dl.download_button("Scarica GPX", data=archivio.gpx(m["id"], n),
                           file_name=f"{m['nome']}_v{n}.gpx".replace(" ", "_"),
                           mime="application/gpx+xml", width="stretch")
    modificabile = puo_modificare(m)
    try:
        if mostra_archiviate:
            if col_rip.button("Riattiva la gita", width="stretch", disabled=not modificabile):
                archivio.archivia(m["id"], utente, archiviata=False)
                avviso(f"Riattivata: {m['nome']}")
                st.rerun()
        elif col_rip.button("Ripristina questa versione", width="stretch",
                            disabled=n == ultima["n"] or not modificabile):
            nuova = archivio.ripristina(m["id"], n, utente)
            avviso(f"La versione {n} è tornata attuale come versione {nuova}")
            st.rerun()
        if not mostra_archiviate and col_pub.button(f"Pubblica la versione {n}", type="primary", width="stretch",
                                                    disabled=not modificabile or bool(pub and pub["n"] == n),
                                                    help="Diventa la versione che vedono gli operatori"):
            archivio.pubblica(m["id"], n, utente)
            avviso(f"{m['nome']}: pubblicata la versione {n}")
            st.rerun()
    except (ErroreArchivio, ValueError) as e:
        st.error(str(e))
    if st.button(f"▶  Prova la navigazione (versione {n})", help="Apre la guida come la vedrà l'operatore. "
                 "Con \"Prova senza GPS\" la gita scorre da sola."):
        st.session_state.guida = (m["id"], n)
        st.rerun()
    for e in reversed(m.get("eventi", [])):
        st.caption(f"{data_breve(e['data'])}: {e['azione']} da {e['autore']}")


# ================================================================ flotta

def chiave(nome: str) -> str:
    """Chiave delle tabelle modificabili: cambia dopo ogni salvataggio, così la tabella riparte dai dati salvati."""
    return f"{nome}_{st.session_state.get('ver_tabelle', 0)}"


def salvato(testo: str) -> None:
    st.session_state.ver_tabelle = st.session_state.get("ver_tabelle", 0) + 1
    avviso(testo)
    st.rerun()


def conta(gite: list[dict], campo: str) -> dict:
    out: dict = {}
    for g in gite:
        if g.get(campo):
            out[g[campo]] = out.get(g[campo], 0) + 1
    return out


def scheda_flotta():
    tutte = archivio.elenco() + archivio.elenco(archiviate=True) + archivio.elenco(bozze=True)

    if amministratore:
        st.subheader("Cantieri")
        st.caption("Aggiungi una riga per creare un cantiere. La rimessa si scrive come coordinate, "
                   "per esempio 43.8102, 11.1433: servirà a riconoscere i tratti di trasferimento.")
        df = pd.DataFrame([{"id": cid, "Nome": c["nome"],
                            "Rimessa": ", ".join(map(str, c["rimessa"])) if c.get("rimessa") else ""}
                           for cid, c in flotte["cantieri"].items()], columns=["id", "Nome", "Rimessa"])
        mod = st.data_editor(df, num_rows="dynamic", hide_index=True, width="stretch", key=chiave("tab_cantieri"),
                             column_config={"id": None, "Nome": st.column_config.TextColumn(required=True),
                                            "Rimessa": st.column_config.TextColumn(help="lat, lon")})
        if st.button("Salva cantieri", key="salva_cantieri"):
            try:
                archivio.modifica_doc("flotte", an.FLOTTE_VUOTO,
                                      lambda d: an.salva_cantieri(d, righe(mod), conta(tutte, "cantiere")),
                                      "Cantieri aggiornati", utente)
                salvato("Cantieri salvati")
            except (ValueError, ErroreArchivio) as e:
                st.error(str(e))

    if cantiere_sel == TUTTI:
        st.info("Scegli un cantiere nella barra laterale per gestirne mezzi e gite.")
        return
    if cantiere_sel == SENZA:
        st.subheader("Gite senza cantiere")
        st.caption("Assegna ogni gita a un cantiere. Dopo potrai indicarne mezzo, turno e giorni "
                   "scegliendo quel cantiere nella barra laterale.")
        if not flotte["cantieri"]:
            st.warning("Crea prima almeno un cantiere nella tabella qui sopra.")
            return
        gite = [m for m in archivio.elenco() if nel_filtro(m)]
        if not gite:
            st.write("Tutte le gite hanno un cantiere.")
            return
        nomi = {c["nome"]: cid for cid, c in flotte["cantieri"].items()}
        df = pd.DataFrame([{"id": m["id"], "Gita": m["nome"], "Cantiere": None} for m in gite])
        mod = st.data_editor(df, hide_index=True, width="stretch", key=chiave("tab_senza"),
                             column_config={"id": None, "Gita": st.column_config.TextColumn(disabled=True),
                                            "Cantiere": st.column_config.SelectboxColumn(options=sorted(nomi))})
        if st.button("Assegna", type="primary"):
            n = 0
            try:
                for r in righe(mod):
                    if r.get("Cantiere"):
                        n += archivio.assegna(r["id"], utente, cantiere=nomi[r["Cantiere"]])
                salvato(f"Gite assegnate: {n}")
            except ErroreArchivio as e:
                st.error(str(e))
        return

    nome = nome_cantiere(cantiere_sel)
    st.subheader(f"Mezzi di {nome}")
    st.caption("Aggiungi una riga per ogni mezzo. Per togliere un mezzo che ha gite, disattivalo invece di eliminarlo.")
    ids = an.mezzi_del_cantiere(flotte, cantiere_sel)
    df = pd.DataFrame([{"id": mid, "Codice": flotte["mezzi"][mid]["codice"], "Targa": flotte["mezzi"][mid].get("targa", ""),
                        "Tipo": flotte["mezzi"][mid].get("tipo") or None, "Attivo": flotte["mezzi"][mid].get("attivo", True),
                        "Operatori": ", ".join(an.utenti_del_mezzo(utenti_doc, mid))}
                       for mid in ids], columns=["id", "Codice", "Targa", "Tipo", "Attivo", "Operatori"])
    mod = st.data_editor(df, num_rows="dynamic", hide_index=True, width="stretch", key=chiave(f"tab_mezzi_{cantiere_sel}"),
                         column_config={"id": None,
                                        "Codice": st.column_config.TextColumn(required=True, help="Per esempio 35"),
                                        "Tipo": st.column_config.SelectboxColumn(options=an.TIPI_MEZZO),
                                        "Attivo": st.column_config.CheckboxColumn(default=True),
                                        "Operatori": st.column_config.TextColumn(
                                            disabled=True, help="Chi ha questo mezzo come abituale: si imposta nella scheda Utenti")})
    if st.button("Salva mezzi", key="salva_mezzi"):
        try:
            archivio.modifica_doc("flotte", an.FLOTTE_VUOTO,
                                  lambda d: an.salva_mezzi(d, cantiere_sel, righe(mod), conta(tutte, "mezzo")),
                                  f"{nome}: mezzi aggiornati", utente)
            salvato("Mezzi salvati")
        except (ValueError, ErroreArchivio) as e:
            st.error(str(e))

    st.subheader(f"Gite di {nome}")
    st.caption("Per ogni gita indica mezzo, numero della gita nella giornata, turno e giorni "
               "(per esempio Lun-Sab oppure Lun Mer Ven).")
    gite = sorted([m for m in archivio.elenco() if m.get("cantiere") == cantiere_sel], key=ordine)
    if not gite:
        st.write("Nessuna gita in questo cantiere. Caricale dalla barra laterale o assegnale dalla voce \"Senza cantiere\".")
        return
    codici = {an.etichetta_mezzo(flotte, mid): mid for mid in an.mezzi_del_cantiere(flotte, cantiere_sel)}
    per_id = {v: k for k, v in codici.items()}
    cantieri_nomi = {c["nome"]: cid for cid, c in flotte["cantieri"].items()}
    colonne = {"id": None, "Gita": st.column_config.TextColumn(disabled=True),
               "Mezzo": st.column_config.SelectboxColumn(options=list(codici)),
               "N. gita": st.column_config.NumberColumn(min_value=1, max_value=20, step=1),
               "Turno": st.column_config.SelectboxColumn(options=an.TURNI),
               "Giorni": st.column_config.TextColumn(help="Lun-Sab, Lun Mer Ven, Tutti i giorni"),
               "Pubblicata": st.column_config.TextColumn(disabled=True, help="Versione che vedono gli operatori")}
    dati = [{"id": m["id"], "Gita": m["nome"], "Mezzo": per_id.get(m.get("mezzo")), "N. gita": m.get("numero"),
             "Turno": m.get("turno"), "Giorni": an.scrivi_giorni(m.get("giorni")), "Pubblicata": stato_pubblicazione(m)}
            for m in gite]
    if amministratore:
        colonne["Cantiere"] = st.column_config.SelectboxColumn(options=sorted(cantieri_nomi),
                                                               help="Per spostare la gita in un altro cantiere")
        for d in dati:
            d["Cantiere"] = nome
    mod = st.data_editor(pd.DataFrame(dati), hide_index=True, width="stretch", key=chiave(f"tab_gite_{cantiere_sel}"),
                         column_config=colonne)
    if st.button("Salva gite", type="primary", key="salva_gite"):
        try:
            n = 0
            for r in righe(mod):
                campi = {"mezzo": codici.get(r.get("Mezzo")), "turno": r.get("Turno"),
                         "numero": int(r["N. gita"]) if r.get("N. gita") is not None else None,
                         "giorni": an.leggi_giorni(r.get("Giorni"))}
                if amministratore and r.get("Cantiere") and cantieri_nomi[r["Cantiere"]] != cantiere_sel:
                    campi.update(cantiere=cantieri_nomi[r["Cantiere"]], mezzo=None)
                n += archivio.assegna(r["id"], utente, **campi)
            salvato(f"Gite aggiornate: {n}")
        except (ValueError, ErroreArchivio) as e:
            st.error(str(e))

    da_pubblicare = [m for m in gite if (m.get("pubblicata") or {}).get("n") != m["versioni"][-1]["n"]]
    if da_pubblicare:
        with st.expander(f"Pubblicazione rapida: {len(da_pubblicare)} gite con una versione non pubblicata"):
            st.write("Pubblica in un colpo l'ultima versione di queste gite. Fallo solo se le hai controllate: "
                     "da quel momento sono quelle che vedono gli operatori.")
            st.caption(", ".join(m["nome"] for m in da_pubblicare))
            conferma = st.checkbox("Le ho controllate")
            if st.button("Pubblica le ultime versioni", disabled=not conferma):
                try:
                    for m in da_pubblicare:
                        archivio.pubblica(m["id"], m["versioni"][-1]["n"], utente)
                    salvato(f"Pubblicate {len(da_pubblicare)} gite")
                except (ValueError, ErroreArchivio) as e:
                    st.error(str(e))


def stato_pubblicazione(m: dict) -> str:
    pub, ultima = m.get("pubblicata"), m["versioni"][-1]["n"]
    if not pub:
        return "No"
    return f"v{pub['n']}" + (f" (ultima v{ultima})" if pub["n"] != ultima else "")


# ================================================================ nuove gite e archivio

def stato_gita(m: dict) -> str:
    if m.get("archiviata"):
        return "Nel cestino"
    if m.get("stato") == "bozza":
        return "Progetto in corso"
    pub, ultima = m.get("pubblicata"), m["versioni"][-1]["n"]
    if not pub:
        return "Conclusa, da pubblicare"
    return f"In strada (v{pub['n']})" + (f", v{ultima} da pubblicare" if pub["n"] != ultima else "")


def scheda_nuove_gite():
    if not miei_cantieri:
        st.info("Non hai cantieri assegnati.")
        return
    st.markdown("<div class='titolo-pagina'><b>Nuove gite</b><span>per creare gite senza GPX, disegnandole sulla mappa"
                "</span></div>", unsafe_allow_html=True)
    cant = st.selectbox("Cantiere", miei_cantieri, format_func=nome_cantiere, key="nuove_cantiere",
                        index=miei_cantieri.index(cantiere_sel) if cantiere_sel in miei_cantieri else 0)
    c1, c2 = st.columns([2, 1])
    url = f"./?area=crea&c={cant}&t={nuovo_gettone(chi)}"
    c1.link_button("🗺️  Apri l'area di progettazione in una nuova finestra", url, type="primary", width="stretch")
    if c2.button("Apri qui", width="stretch", help="Se il browser blocca le nuove finestre"):
        st.session_state.pagina = "crea"
        st.session_state.crea_cantiere_iniziale = cant
        st.rerun()
    st.caption("Nell'area di progettazione disegni il percorso, aggiungi i punti d'interesse e salvi la bozza. "
               "I progetti salvati restano qui sotto finché non li concludi: a quel punto passano tra le gite del "
               "cantiere, pronti per essere pubblicati.")
    bozze = [m for m in archivio.elenco(bozze=True) if m.get("cantiere") == cant]
    st.subheader(f"Progetti in corso: {len(bozze)}")
    if not bozze:
        st.write("Nessun progetto in corso in questo cantiere.")
        return
    for m in sorted(bozze, key=lambda x: x["versioni"][-1]["data"], reverse=True):
        v = m["versioni"][-1]
        with st.container(border=True):
            a, b = st.columns([4, 1], vertical_alignment="center")
            a.markdown(f"**{m['nome']}**  \n:gray[{v['km_tot']:.1f} km, {v.get('note_mappa', 0)} punti d'interesse, "
                       f"salvato il {data_breve(v['data'])} da {v['autore']}]".replace(".", ",", 1))
            if b.button("Elimina", key=f"del_bozza_{m['id']}", width="stretch", disabled=not puo_modificare(m)):
                archivio.archivia(m["id"], utente)
                avviso(f"Progetto \"{m['nome']}\" spostato nel cestino")
                st.rerun()


def scheda_archivio():
    opzioni = miei_cantieri + ([SENZA] if amministratore else [])
    if not opzioni:
        st.info("Non hai cantieri assegnati.")
        return
    st.markdown("<div class='titolo-pagina'><b>Archivio gite</b><span>tutti i file del cantiere: progetti, gite "
                "concluse, gite in strada e cestino</span></div>", unsafe_allow_html=True)
    c1, c2 = st.columns([1, 2])
    cant = c1.selectbox("Cantiere", opzioni, format_func=nome_cantiere, key="arch_cantiere",
                        index=opzioni.index(cantiere_sel) if cantiere_sel in opzioni else 0)
    filtro = c2.segmented_control("Mostra", ["Tutte", "Progetti in corso", "Concluse", "In strada", "Nel cestino"],
                                  default="Tutte", key="arch_filtro")
    def del_cantiere(m):
        return (m.get("cantiere") is None or m.get("cantiere") not in flotte["cantieri"]) if cant == SENZA \
            else m.get("cantiere") == cant
    tutte = [m for m in archivio.tutte() if del_cantiere(m)]
    filtri = {"Progetti in corso": lambda m: stato_gita(m) == "Progetto in corso",
              "Concluse": lambda m: stato_gita(m) == "Conclusa, da pubblicare",
              "In strada": lambda m: stato_gita(m).startswith("In strada"),
              "Nel cestino": lambda m: stato_gita(m) == "Nel cestino"}
    gite = [m for m in tutte if filtri.get(filtro or "Tutte", lambda m: True)(m)]
    if not gite:
        st.write("Nessuna gita in questa selezione.")
        return
    df = pd.DataFrame([{"Gita": m["nome"], "Stato": stato_gita(m), "Versioni": len(m["versioni"]),
                        "Ultimo salvataggio": data_breve(m["versioni"][-1]["data"]),
                        "Da": m["versioni"][-1]["autore"], "Km": round(m["versioni"][-1]["km_tot"], 1)} for m in gite])
    evento = st.dataframe(df, hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row",
                          key=chiave(f"arch_{cant}_{filtro}"))
    scelte = [gite[i] for i in evento.selection.rows if i < len(gite)]
    attive_sel = [m for m in scelte if not m.get("archiviata") and puo_modificare(m)]
    cestino_sel = [m for m in scelte if m.get("archiviata") and puo_modificare(m)]
    st.caption(f"Selezionate: {len(scelte)}" if scelte else
               "Clicca sulla casella a sinistra di una o più gite per selezionarle.")
    b1, b2, b3, b4 = st.columns(4)
    try:
        if b1.button(f"Sposta nel cestino ({len(attive_sel)})", disabled=not attive_sel, width="stretch"):
            for m in attive_sel:
                archivio.archivia(m["id"], utente)
            salvato(f"Spostate nel cestino: {len(attive_sel)}")
        if b2.button(f"Ripristina ({len(cestino_sel)})", disabled=not cestino_sel, width="stretch"):
            for m in cestino_sel:
                archivio.archivia(m["id"], utente, archiviata=False)
            salvato(f"Ripristinate: {len(cestino_sel)}")
        b3.download_button(f"Scarica GPX ({len(scelte)})", disabled=not scelte, width="stretch",
                           data=archivio.zip_ultime(scelte) if scelte else b"", mime="application/zip",
                           file_name=f"gite_{datetime.now():%Y%m%d}.zip")
        if amministratore:
            with b4.popover(f"Elimina definitivamente ({len(cestino_sel)})", disabled=not cestino_sel,
                            width="stretch"):
                st.write("Le gite e **tutte le loro versioni** saranno cancellate e non si potranno recuperare:")
                st.write(", ".join(m["nome"] for m in cestino_sel))
                if st.button("Sì, elimina definitivamente", type="primary"):
                    for m in cestino_sel:
                        archivio.elimina_definitivamente(m["id"], utente)
                    salvato(f"Eliminate definitivamente: {len(cestino_sel)}")
        else:
            b4.caption("L'eliminazione definitiva dal cestino è riservata all'amministratore.")
    except (ErroreArchivio, ValueError) as e:
        st.error(str(e))
    if scelte and any(not m.get("archiviata") for m in scelte):
        st.caption("Per eliminare definitivamente una gita, prima spostala nel cestino.")


# ================================================================ utenti (solo amministratore)

def scheda_utenti():
    utenti = utenti_doc["utenti"]
    cantieri_nomi = {c["nome"]: cid for cid, c in flotte["cantieri"].items()}
    nome_di = {cid: n for n, cid in cantieri_nomi.items()}
    tutti_mezzi = [None] + sorted(flotte["mezzi"], key=lambda k: (nome_di.get(flotte["mezzi"][k]["cantiere"], ""),
                                                                   an._ordinabile(flotte["mezzi"][k]["codice"])))

    def nome_mezzo(k):
        if not k:
            return "Nessuno"
        return f"{nome_di.get(flotte['mezzi'][k]['cantiere'], '?')}: {an.etichetta_mezzo(flotte, k)}"

    if ADMIN:
        st.caption(f"Oltre a questi utenti, l'accesso '{ADMIN.get('utente')}' dei Secrets è sempre amministratore: "
                   "tienilo come accesso di emergenza.")
    if utenti:
        st.dataframe([{"Utente": k, "Nome": u["nome"], "Ruolo": an.RUOLI.get(u["ruolo"], u["ruolo"]),
                       "Cantieri": "Tutti" if u["ruolo"] == "amministratore"
                       else ", ".join(nome_di.get(c, "?") for c in u.get("cantieri", [])),
                       "Mezzo abituale": nome_mezzo(u.get("mezzo")) if u.get("mezzo") in flotte["mezzi"] else "",
                       "Attivo": "Sì" if u.get("attivo", True) else "No"} for k, u in sorted(utenti.items())],
                     hide_index=True, width="stretch")
    else:
        st.write("Nessun utente ancora. Crea il primo qui sotto.")

    c1, c2 = st.columns(2)
    with c1, st.form("nuovo_utente", clear_on_submit=True):
        st.subheader("Nuovo utente")
        nu = st.text_input("Nome utente", help="Minuscole, numeri, punto o trattino. Per esempio mario.rossi")
        nn = st.text_input("Nome e cognome")
        nr = st.selectbox("Ruolo", list(an.RUOLI), format_func=an.RUOLI.get, index=1)
        nc = st.multiselect("Cantieri", sorted(cantieri_nomi), help="Non serve per gli amministratori")
        nm = st.selectbox("Mezzo abituale", tutti_mezzi, format_func=nome_mezzo,
                          help="Per gli operatori: il mezzo che guidano di solito")
        npw = st.text_input("Password iniziale", type="password", help="Almeno 8 caratteri. Comunicala di persona.")
        if st.form_submit_button("Crea utente", type="primary"):
            try:
                cs = [cantieri_nomi[x] for x in nc]
                an.controlla_mezzo(flotte, nm, cs)
                archivio.modifica_doc("utenti", an.UTENTI_VUOTO,
                                      lambda d: an.crea_utente(d, nu, nn, nr, cs, npw, mezzo=nm),
                                      f"Nuovo utente {nu}", utente)
                avviso(f"Utente {nu} creato")
                st.rerun()
            except (ValueError, ErroreArchivio) as e:
                st.error(str(e))
    with c2:
        st.subheader("Modifica utente")
        if not utenti:
            st.write("Nessun utente da modificare.")
            return
        scelto = st.selectbox("Utente", sorted(utenti), format_func=lambda k: f"{utenti[k]['nome']} ({k})")
        u = utenti[scelto]
        with st.form(f"modifica_{scelto}"):
            mn = st.text_input("Nome e cognome", u["nome"])
            mr = st.selectbox("Ruolo", list(an.RUOLI), format_func=an.RUOLI.get, index=list(an.RUOLI).index(u["ruolo"]))
            mc = st.multiselect("Cantieri", sorted(cantieri_nomi),
                                default=[nome_di[c] for c in u.get("cantieri", []) if c in nome_di])
            mm = st.selectbox("Mezzo abituale", tutti_mezzi, format_func=nome_mezzo,
                              index=tutti_mezzi.index(u["mezzo"]) if u.get("mezzo") in tutti_mezzi else 0)
            ma = st.checkbox("Attivo", u.get("attivo", True))
            mpw = st.text_input("Nuova password", type="password", help="Lascia vuoto per non cambiarla")
            if st.form_submit_button("Salva"):
                try:
                    cs = [cantieri_nomi[x] for x in mc]
                    an.controlla_mezzo(flotte, mm, cs)
                    archivio.modifica_doc("utenti", an.UTENTI_VUOTO,
                                          lambda d: an.aggiorna_utente(d, scelto, mn, mr, cs, ma, mpw, mezzo=mm),
                                          f"Utente {scelto} aggiornato", utente)
                    avviso(f"Utente {scelto} aggiornato")
                    st.rerun()
                except (ValueError, ErroreArchivio) as e:
                    st.error(str(e))


# ================================================================ operatori

def scheda_operatore():
    st.markdown(f"<div class='titolo-pagina'><b>Gite di {nome_cantiere(cantiere_sel)}</b>"
                "<span>scegli la gita e avvia la navigazione</span></div>", unsafe_allow_html=True)
    gite = sorted([m for m in archivio.elenco() if m.get("cantiere") == cantiere_sel and m.get("pubblicata")],
                  key=lambda m: m["nome"].lower())
    if not gite:
        st.info("In questo cantiere non ci sono ancora gite pronte per la strada. "
                "Chiedi al responsabile di pubblicarle.")
        return
    cerca = st.text_input("Cerca", placeholder="Cerca una gita per nome", label_visibility="collapsed")
    if cerca.strip():
        gite = [m for m in gite if cerca.strip().lower() in m["nome"].lower()]
        if not gite:
            st.write("Nessuna gita con questo nome.")
    for m in gite:
        pub = m["pubblicata"]
        v = next(x for x in m["versioni"] if x["n"] == pub["n"])
        with st.container(border=True):
            st.markdown(f"**{m['nome']}**")
            dettagli = [f"{v['km_tot']:.1f} km".replace(".", ",")]
            if v.get("note_mappa"):
                dettagli.append(f"{v['note_mappa']} punti d'interesse")
            st.caption(", ".join(dettagli))
            c1, c2 = st.columns([3, 1])
            if c1.button("▶  Avvia navigazione", key=f"nav_{m['id']}", type="primary", width="stretch"):
                st.session_state.guida = (m["id"], pub["n"])
                st.rerun()
            c2.download_button("GPX", data=archivio.gpx(m["id"], pub["n"]), key=f"dl_{m['id']}",
                               file_name=f"{m['nome']}.gpx".replace(" ", "_"), mime="application/gpx+xml",
                               width="stretch", help="Per aprire la gita in un'altra app, per esempio OsmAnd")


def pagina_guida(gid: str, n: int):
    st.markdown("<style>[data-testid='stSidebar'],[data-testid='stSidebarCollapsedControl'],"
                "[data-testid='stExpandSidebarButton'],header[data-testid='stHeader']{display:none!important}"
                ".block-container{padding:0.4rem 0.4rem 0!important}"
                "iframe[title='app.guida_percorsi']{border-radius:10px}</style>", unsafe_allow_html=True)
    try:
        m = archivio.meta(gid)
        pts, wpts = contenuto_versione(gid, n)
    except (FileNotFoundError, StopIteration, ValueError):
        st.session_state.pop("guida", None)
        st.rerun()
    if st.button("← Torna alle gite"):
        st.session_state.pop("guida", None)
        st.rerun()
    risposta = guida(gita={"id": gid, "version": n, "name": m["nome"], "pts": pts, "wpts": wpts},
                     key=f"guida_{gid}_{n}", default=None)
    if risposta and risposta.get("azione") == "chiudi" and risposta.get("nonce") != st.session_state.get("guida_nonce"):
        st.session_state.guida_nonce = risposta["nonce"]
        st.session_state.pop("guida", None)
        st.rerun()


# ================================================================ schede

if st.session_state.get("guida"):
    pagina_guida(*st.session_state.guida)
elif ruolo == "operatore":
    scheda_operatore()
elif st.session_state.get("pagina") == "crea" and miei_cantieri:
    pagina_crea()
else:
    nomi = ["Editor", "Nuove gite", "Archivio gite", "Storico versioni", "Flotta"] + (["Utenti"] if amministratore else [])
    schede = dict(zip(nomi, st.tabs(nomi)))
    with schede["Editor"]:
        scheda_editor()
    with schede["Nuove gite"]:
        scheda_nuove_gite()
    with schede["Archivio gite"]:
        scheda_archivio()
    with schede["Storico versioni"]:
        scheda_storico()
    with schede["Flotta"]:
        scheda_flotta()
    if amministratore:
        with schede["Utenti"]:
            scheda_utenti()
