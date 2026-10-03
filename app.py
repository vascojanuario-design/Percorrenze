"""Portale percorsi: correzione condivisa delle gite di raccolta, organizzate per cantiere e mezzo.

Avvio:  streamlit run app.py
Configurazione nei secrets (vedi README): [archivio] per dove salvare, [amministratore] per il primo accesso.
"""
import base64
import math
import os
import secrets as segreto
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import anagrafica as an
import strade
from archivio import Conflitto, ErroreArchivio, apri, distanza, leggi_gpx, leggi_waypoint, pulisci

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
.titolo-pagina b{font-size:1.65rem;white-space:nowrap;letter-spacing:-.01em}
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
CHIAVE_STRADE = segreti("openrouteservice").get("chiave", "")


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


def barra_laterale_fondo():
    with st.sidebar:
        st.divider()
        if not chi.get("da_secrets"):
            with st.expander("Cambia password", icon=":material/key:"):
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
        if st.button("Esci", icon=":material/logout:", width="stretch"):
            st.session_state.clear()
            st.rerun()


for testo, ok in st.session_state.pop("avvisi", []):
    st.toast(testo, icon="✅" if ok else "⚠️")

if not cantiere_sel:
    st.stop()


# ================================================================ gite del cantiere scelto

def nel_filtro(m: dict, mezzo: str = TUTTI) -> bool:
    c = m.get("cantiere")
    if cantiere_sel == TUTTI:
        ok = True
    elif cantiere_sel == SENZA:
        ok = c is None or c not in flotte["cantieri"]
    else:
        ok = c == cantiere_sel
    if ok and mezzo == SENZA:
        ok = not m.get("mezzo") or m.get("mezzo") not in flotte["mezzi"]
    elif ok and mezzo != TUTTI:
        ok = m.get("mezzo") == mezzo
    return ok


def ordine(m: dict):
    v = flotte["mezzi"].get(m.get("mezzo") or "", {})
    return (an._ordinabile(v.get("codice", "zzz")), m.get("numero") or 99, m["nome"].lower())


@st.cache_data(show_spinner=False, max_entries=50)
def contenuto_versione(gid: str, versione: int) -> tuple[list, list]:
    return archivio.contenuto(gid, versione)


def gestisci(risposta, dest_cantiere: str | None, dest_mezzo: str | None) -> None:
    """Esegue sul server le azioni chieste dall'editor (salva, crea, concludi, archivia) e risponde all'editor."""
    if not risposta or risposta.get("nonce") == st.session_state.get("ultimo_nonce"):
        return
    st.session_state.ultimo_nonce = risposta["nonce"]
    azione, gid, nonce, stato = risposta.get("action"), risposta.get("gita_id"), risposta["nonce"], risposta.get("stato")
    if azione == "instrada":
        try:
            punti = strade.instrada(CHIAVE_STRADE, risposta["da"], risposta["a"])
            st.session_state.instr = {"nonce": nonce, "punti": punti}
        except strade.ErroreStrade as e:
            st.session_state.instr = {"nonce": nonce, "errore": str(e)}
        st.rerun()
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
                testo = f"Gita \"{nome}\" conclusa: ora è tra le gite del cantiere e gli operatori la vedono"
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
    testa = st.columns([1.3, 3, 2, 2], vertical_alignment="bottom")
    if testa[0].button("🏠  Home", type="primary", width="stretch",
                       help="Torna al portale. Salva prima la bozza: le modifiche non salvate restano solo su questo computer"):
        st.session_state.pagina = None
        st.session_state.finestra_separata = False
        st.rerun()
    testa[1].markdown("<div class='titolo-pagina'><b>Area di progettazione</b>"
                      "<span>disegna il percorso e i punti d'interesse</span></div>", unsafe_allow_html=True)
    iniziale = st.session_state.pop("crea_cantiere_iniziale", None)
    if iniziale in miei_cantieri:
        st.session_state.crea_cantiere = iniziale
    cant = testa[2].selectbox("Cantiere", miei_cantieri, format_func=nome_cantiere, key="crea_cantiere",
                              index=miei_cantieri.index(cantiere_sel) if cantiere_sel in miei_cantieri else 0)
    mezzi = [None] + an.mezzi_del_cantiere(flotte, cant, solo_attivi=True)
    mez = testa[3].selectbox("Mezzo", mezzi, key=f"crea_mezzo_{cant}",
                             format_func=lambda k: "Da decidere" if not k else an.etichetta_mezzo(flotte, k))
    bozze = sorted([m for m in archivio.elenco(bozze=True) if m.get("cantiere") == cant], key=lambda m: m["nome"].lower())
    risposta = editor(data=dati_per_editor(bozze), data_version=f"{archivio.impronta()}|crea|{cant}", user=utente,
                      msg=st.session_state.get("msg"), height=ALTEZZA_EDITOR, mode="crea",
                      seleziona=st.session_state.get("crea_seleziona"), strade=bool(CHIAVE_STRADE),
                      instradamento=st.session_state.get("instr"), key="editor_crea", default=None)
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
    intestazione("Cantieri e mezzi", "cantieri con la rimessa, mezzi e assegnazione delle gite")
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
               "Operatori": st.column_config.TextColumn(disabled=True, help="Versione che vedono gli operatori")}
    dati = [{"id": m["id"], "Gita": m["nome"], "Mezzo": per_id.get(m.get("mezzo")), "N. gita": m.get("numero"),
             "Turno": m.get("turno"), "Giorni": an.scrivi_giorni(m.get("giorni")), "Operatori": stato_pubblicazione(m)}
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


def stato_pubblicazione(m: dict) -> str:
    pub, ultima = m.get("pubblicata"), m["versioni"][-1]["n"]
    return f"v{pub['n']} fissata" if pub else f"ultima (v{ultima})"


# ================================================================ nuove gite e archivio

def versione_operatori(m: dict) -> int:
    """Gli operatori usano la versione fissata, se c'è, altrimenti sempre l'ultima."""
    return (m.get("pubblicata") or {}).get("n") or m["versioni"][-1]["n"]


def stato_gita(m: dict) -> str:
    if m.get("archiviata"):
        return "Nel cestino"
    if m.get("stato") == "bozza":
        return "Progetto in corso"
    pub, ultima = m.get("pubblicata"), m["versioni"][-1]["n"]
    if pub and pub["n"] != ultima:
        return f"Attiva, operatori fissati alla v{pub['n']} (ultima v{ultima})"
    return "Attiva"


def scheda_nuove_gite():
    if not miei_cantieri:
        st.info("Non hai cantieri assegnati.")
        return
    intestazione("Nuove gite", "per creare gite senza GPX, disegnandole sulla mappa")
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
               "cantiere e gli operatori li vedono subito.")
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


# ================================================================ elementi grafici comuni

def intestazione(titolo: str, sottotitolo: str = "") -> None:
    st.markdown(f"<div class='titolo-pagina'><b>{titolo}</b><span>{sottotitolo}</span></div>", unsafe_allow_html=True)


@st.cache_data(show_spinner=False, max_entries=400)
def svg_gita(gid: str, versione: int, larg: int = 160, alt: int = 100, spessore: float = 2.2) -> str:
    """Piccolo disegno del percorso: raccolta in verde, trasferimento grigio tratteggiato."""
    pts, wpts = contenuto_versione(gid, versione)
    if len(pts) < 2:
        return f"<svg xmlns='http://www.w3.org/2000/svg' width='{larg}' height='{alt}'></svg>"
    passo = max(1, len(pts) // 400)
    camp = pts[::passo] + [pts[-1]]
    k = math.cos(math.radians(camp[0][0]))
    xs = [p[1] * k for p in camp]; ys = [p[0] for p in camp]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    m = 6
    sc = min((larg - 2 * m) / ((maxx - minx) or 1e-9), (alt - 2 * m) / ((maxy - miny) or 1e-9))
    ox = (larg - (maxx - minx) * sc) / 2; oy = (alt - (maxy - miny) * sc) / 2
    xy = [(ox + (x - minx) * sc, alt - (oy + (y - miny) * sc)) for x, y in zip(xs, ys)]
    tratti, attuale, tipo = [], [xy[0]], camp[0][2]
    for (x, y), p in zip(xy[1:], camp[1:]):
        attuale.append((x, y))
        if p[2] != tipo:
            tratti.append((tipo, attuale)); attuale = [(x, y)]; tipo = p[2]
    tratti.append((tipo, attuale))
    linee = "".join(
        f"<polyline points='{' '.join(f'{x:.1f},{y:.1f}' for x, y in t)}' fill='none' "
        + (f"stroke='#8A9590' stroke-width='{spessore * .8}' stroke-dasharray='3 3'" if tp == "t"
           else f"stroke='#009640' stroke-width='{spessore}'") + " stroke-linejoin='round' stroke-linecap='round'/>"
        for tp, t in tratti if len(t) > 1)
    (x0, y0), (x1, y1) = xy[0], xy[-1]
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{larg}' height='{alt}' viewBox='0 0 {larg} {alt}'>"
            f"<rect width='{larg}' height='{alt}' rx='8' fill='#EEF5F0'/>{linee}"
            f"<circle cx='{x0:.1f}' cy='{y0:.1f}' r='{spessore * 1.6}' fill='#16301F'/>"
            f"<rect x='{x1 - spessore * 1.5:.1f}' y='{y1 - spessore * 1.5:.1f}' width='{spessore * 3}' height='{spessore * 3}' fill='#16301F'/></svg>")


def svg_html(gid: str, versione: int, larg: int = 220, alt: int = 120, spessore: float = 2.2) -> str:
    """Anteprima che si adatta alla larghezza del riquadro."""
    svg = svg_gita(gid, versione, larg, alt, spessore)
    return svg.replace(f"width='{larg}' height='{alt}' viewBox", "style='width:100%;height:auto;display:block' viewBox", 1)


def svg_dati(gid: str, versione: int, larg: int = 160, alt: int = 100) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg_gita(gid, versione, larg, alt).encode()).decode()


@st.cache_data(show_spinner=False, max_entries=400)
def n_segnalazioni(gid: str, versione: int) -> int:
    """Come "Da verificare" nell'editor: segmenti oltre 250 m e brevi andata e ritorno sotto i 30 m."""
    pts, _ = contenuto_versione(gid, versione)
    n = 0
    for a, b in zip(pts, pts[1:]):
        if distanza(a, b) > 250:
            n += 1
    for a, b, c in zip(pts, pts[1:], pts[2:]):
        d1, d2 = distanza(a, b), distanza(b, c)
        if 3 <= d1 < 30 and 3 <= d2 < 30:
            k = math.cos(math.radians(b[0]))
            v1 = ((b[1] - a[1]) * k, b[0] - a[0]); v2 = ((c[1] - b[1]) * k, c[0] - b[0])
            if (v1[0] * v2[0] + v1[1] * v2[1]) / (math.hypot(*v1) * math.hypot(*v2)) < -0.9:
                n += 1
    return n


ETICHETTE_STATO = {"Attiva": ":green-badge[Attiva]", "Progetto in corso": ":orange-badge[Progetto in corso]",
                   "Nel cestino": ":gray-badge[Nel cestino]"}


def badge_stato(m: dict) -> str:
    s = stato_gita(m)
    return ETICHETTE_STATO.get(s, f":blue-badge[{s}]")


def carica_gpx(dest_cantiere: str | None, chiave_ui: str) -> None:
    st.caption(f"Le gite caricate andranno in: **{nome_cantiere(dest_cantiere)}**")
    chiave_upload = f"upload_{chiave_ui}_{st.session_state.get('upload_n', 0)}"
    nuovi = st.file_uploader("File GPX, Excel o CSV", type=["gpx", "xlsx", "xls", "csv"], accept_multiple_files=True,
                             key=chiave_upload, label_visibility="collapsed")
    st.caption("Da Excel o CSV servono le colonne di **latitudine** e **longitudine**, nell'ordine di percorrenza. "
               "Facoltative: gita (una gita per ogni nome), ordine, tipo (raccolta/trasferimento), lato "
               "(destro/sinistro/entrambi), nota.")
    if nuovi and st.button("Importa", type="primary", width="stretch", key=f"importa_{chiave_ui}"):
        for f in nuovi:
            try:
                if f.name.lower().endswith(".gpx"):
                    nome, pts = leggi_gpx(f.getvalue(), f.name)
                    gite_file = [{"nome": nome, "punti": pts, "waypoint": leggi_waypoint(f.getvalue())}]
                else:
                    gite_file = strade.leggi_tabella(f.getvalue(), f.name)
                for g in gite_file:
                    pts, rimossi = pulisci(g["punti"])
                    archivio.crea(g["nome"], pts, utente,
                                  f"Importata da {f.name}" + (f", rimossi {rimossi} punti doppi" if rimossi else ""),
                                  cantiere=dest_cantiere, waypoint=g["waypoint"])
                    avviso(f"Importata: {g['nome']}")
            except (ValueError, ErroreArchivio) as e:
                avviso(str(e), ok=False)
        st.session_state.upload_n = st.session_state.get("upload_n", 0) + 1
        st.rerun()


def vai_a(pagina: str, **stato) -> None:
    for k, v in stato.items():
        st.session_state[k] = v
    st.switch_page(PAGINE[pagina])


def scadenza_token() -> datetime | None:
    testo = getattr(archivio.d, "scadenza_token", None)
    if not testo:
        return None
    try:
        return datetime.strptime(testo.replace(" UTC", "").strip()[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def avvisi_sistema() -> list[str]:
    out = []
    if amministratore and "GitHub" not in archivio.descrizione and segreti("archivio").get("tipo") != "locale" \
            and "mount/src" in archivio.descrizione:
        out.append("**L'archivio non sta salvando su GitHub**: le modifiche si perderanno al prossimo riavvio. "
                   "Controlla la sezione [archivio] nei Secrets (vedi Impostazioni).")
    sc = scadenza_token()
    if amministratore and sc:
        giorni = (sc - datetime.now()).days
        if giorni < 30:
            out.append(f"Il token di GitHub **scade fra {max(giorni, 0)} giorni** ({sc:%d/%m/%Y}): rigeneralo e "
                       "aggiorna i Secrets, altrimenti il portale smetterà di salvare.")
    return out


# ================================================================ home

def pagina_home():
    ora = an.adesso().hour
    saluto = "Buongiorno" if ora < 13 else "Buon pomeriggio" if ora < 18 else "Buonasera"
    intestazione(f"{saluto}, {chi['nome'].split()[0]}", f"cantiere: {nome_cantiere(cantiere_sel)}")
    for a in avvisi_sistema():
        st.warning(a, icon=":material/warning:")
    if cantiere_sel not in (TUTTI, SENZA) and not flotte["cantieri"].get(cantiere_sel, {}).get("rimessa"):
        st.info("Per questo cantiere non è indicata la posizione della rimessa: puoi aggiungerla in "
                "**Cantieri e mezzi**.", icon=":material/info:")
    if amministratore:
        senza = [m for m in archivio.elenco() if not m.get("cantiere") or m.get("cantiere") not in flotte["cantieri"]]
        if senza:
            st.info(f"Ci sono **{len(senza)} gite senza cantiere**: scegli \"Senza cantiere\" nella barra laterale e "
                    "assegnale in Cantieri e mezzi.", icon=":material/info:")

    gite = sorted([m for m in archivio.elenco() if nel_filtro(m)], key=ordine)
    bozze = [m for m in archivio.elenco(bozze=True) if nel_filtro(m)]
    km_r = sum(m["versioni"][-1]["km_raccolta"] for m in gite)
    km_t = sum(m["versioni"][-1]["km_trasferimento"] for m in gite)
    da_verif = sum(n_segnalazioni(m["id"], m["versioni"][-1]["n"]) for m in gite)
    c = st.columns(5)
    c[0].metric("Gite attive", len(gite), border=True)
    c[1].metric("Km di raccolta", f"{km_r:.1f}".replace(".", ","), border=True)
    c[2].metric("Km di trasferimento", f"{km_t:.1f}".replace(".", ","), border=True)
    c[3].metric("Progetti in corso", len(bozze), border=True)
    c[4].metric("Segnalazioni da verificare", da_verif, border=True,
                help="Segmenti lunghi senza punti e brevi andata e ritorno, come nell'editor")

    a1, a2, a3, a4 = st.columns(4)
    if a1.button("Nuova gita", icon=":material/add_road:", width="stretch", type="primary"):
        vai_a("nuove")
    if a2.button("Carica GPX o Excel", icon=":material/upload_file:", width="stretch"):
        vai_a("elenco", apri_caricamento=True)
    if a3.button("Elenco gite", icon=":material/list:", width="stretch"):
        vai_a("elenco")
    if a4.button("Percorrenze", icon=":material/navigation:", width="stretch"):
        vai_a("percorrenze")

    sx, dx = st.columns([3, 2], gap="large")
    with sx:
        st.subheader("Gite del cantiere")
        if not gite:
            st.write("Nessuna gita. Caricale da GPX o disegnale in **Nuove gite**.")
        for riga in range(0, min(len(gite), 9), 3):
            cols = st.columns(3)
            for col, m in zip(cols, gite[riga:riga + 3]):
                v = m["versioni"][-1]
                with col.container(border=True):
                    st.markdown(svg_html(m["id"], v["n"], 220, 120), unsafe_allow_html=True)
                    st.markdown(f"**{m['nome']}**  \n:gray[{v['km_tot']:.1f} km]".replace(".", ",", 1))
                    if st.button("Apri", key=f"home_apri_{m['id']}", width="stretch"):
                        vai_a("elenco", elenco_cerca=m["nome"])
        if len(gite) > 9:
            st.caption(f"E altre {len(gite) - 9} gite nell'**Elenco gite**.")
    with dx:
        st.subheader("Attività recente")
        eventi = []
        for m in archivio.tutte():
            if not nel_filtro(m):
                continue
            for v in m["versioni"]:
                eventi.append((v["data"], m["nome"], v["autore"], f"versione {v['n']}: {v['nota']}"))
            for e in m.get("eventi", []):
                eventi.append((e["data"], m["nome"], e["autore"], e["azione"]))
        if not eventi:
            st.write("Ancora nessuna attività.")
        for data, nome, autore, cosa in sorted(eventi, reverse=True)[:10]:
            st.markdown(f"**{nome}**  \n:gray[{data_breve(data)}, {autore}: {cosa}]")


# ================================================================ elenco gite e scheda della gita

def pagina_elenco():
    intestazione("Elenco gite", "cerca una gita, aprila e gestiscila: modifica, rinomina, versioni, cestino")
    c1, c2, c3 = st.columns([2.2, 3, 1.4], vertical_alignment="bottom")
    cerca = c1.text_input("Cerca", placeholder="Cerca per nome", label_visibility="collapsed", key="elenco_cerca")
    filtro = c2.segmented_control("Mostra", ["Attive", "Progetti in corso", "Nel cestino", "Tutte"], default="Attive",
                                  key="elenco_filtro", label_visibility="collapsed")
    if ruolo != "operatore":
        dest = cantiere_sel if cantiere_sel not in (TUTTI, SENZA) else None
        with c3.popover("Carica GPX o Excel", icon=":material/upload_file:", width="stretch"):
            carica_gpx(dest, "elenco")
    if st.session_state.pop("apri_caricamento", False):
        st.info("Usa il pulsante **Carica GPX o Excel** qui sopra a destra.", icon=":material/upload_file:")

    tutte = [m for m in archivio.tutte() if nel_filtro(m)]
    filtri = {"Attive": lambda m: stato_gita(m).startswith("Attiva"),
              "Progetti in corso": lambda m: stato_gita(m) == "Progetto in corso",
              "Nel cestino": lambda m: stato_gita(m) == "Nel cestino"}
    gite = [m for m in tutte if filtri.get(filtro or "Tutte", lambda m: True)(m)]
    if cerca.strip():
        gite = [m for m in gite if cerca.strip().lower() in m["nome"].lower()]
    gite = sorted(gite, key=ordine)
    if not gite:
        st.write("Nessuna gita in questa selezione.")
        return

    df = pd.DataFrame([{"Anteprima": svg_dati(m["id"], m["versioni"][-1]["n"], 96, 56), "Gita": m["nome"],
                        "Stato": stato_gita(m), "Mezzo": descrizione_gita(m),
                        "Km": round(m["versioni"][-1]["km_tot"], 1), "Versioni": len(m["versioni"]),
                        "Ultima modifica": data_breve(m["versioni"][-1]["data"]),
                        "Da": m["versioni"][-1]["autore"]} for m in gite])
    evento = st.dataframe(df, hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row",
                          row_height=60, key=chiave(f"elenco_{cantiere_sel}_{filtro}_{cerca}"),
                          column_config={"Anteprima": st.column_config.ImageColumn(width="small"),
                                         "Gita": st.column_config.TextColumn(width="medium"),
                                         "Km": st.column_config.NumberColumn(format="%.1f")})
    scelte = [gite[i] for i in evento.selection.rows if i < len(gite)]
    if not scelte and len(gite) == 1 and cerca.strip():
        scelte = gite
    if len(scelte) == 1:
        scheda_gita(scelte[0])
    elif len(scelte) > 1:
        azioni_multiple(scelte)
    else:
        st.caption("Clicca sulla casella a sinistra di una gita per aprire la sua scheda, o di più gite per agire su "
                   "tutte insieme.")


def azioni_multiple(scelte: list[dict]) -> None:
    attive_sel = [m for m in scelte if not m.get("archiviata") and puo_modificare(m)]
    cestino_sel = [m for m in scelte if m.get("archiviata") and puo_modificare(m)]
    with st.container(border=True):
        st.markdown(f"**{len(scelte)} gite selezionate**")
        b1, b2, b3, b4 = st.columns(4)
        try:
            if b1.button(f"Sposta nel cestino ({len(attive_sel)})", icon=":material/delete:",
                         disabled=not attive_sel, width="stretch"):
                for m in attive_sel:
                    archivio.archivia(m["id"], utente)
                salvato(f"Spostate nel cestino: {len(attive_sel)}")
            if b2.button(f"Ripristina ({len(cestino_sel)})", icon=":material/restore_from_trash:",
                         disabled=not cestino_sel, width="stretch"):
                for m in cestino_sel:
                    archivio.archivia(m["id"], utente, archiviata=False)
                salvato(f"Ripristinate: {len(cestino_sel)}")
            b3.download_button(f"Scarica GPX ({len(scelte)})", icon=":material/download:", width="stretch",
                               data=archivio.zip_ultime(scelte), mime="application/zip",
                               file_name=f"gite_{datetime.now():%Y%m%d}.zip")
            if amministratore:
                with b4.popover(f"Elimina definitivamente ({len(cestino_sel)})", icon=":material/delete_forever:",
                                disabled=not cestino_sel, width="stretch"):
                    st.write("Le gite e **tutte le loro versioni** saranno cancellate e non si potranno recuperare:")
                    st.write(", ".join(m["nome"] for m in cestino_sel))
                    if st.button("Sì, elimina definitivamente", type="primary"):
                        for m in cestino_sel:
                            archivio.elimina_definitivamente(m["id"], utente)
                        salvato(f"Eliminate definitivamente: {len(cestino_sel)}")
        except (ErroreArchivio, ValueError) as e:
            st.error(str(e))
        if any(not m.get("archiviata") for m in scelte) and amministratore:
            st.caption("Per eliminare definitivamente una gita, prima spostala nel cestino.")


def scheda_gita(m: dict) -> None:
    ultima = m["versioni"][-1]
    mod = puo_modificare(m)
    bozza, cestino = m.get("stato") == "bozza", bool(m.get("archiviata"))
    with st.container(border=True):
        sx, dx = st.columns([1.1, 2], gap="large")
        sx.markdown(svg_html(m["id"], ultima["n"], 360, 230, 3), unsafe_allow_html=True)
        with dx:
            st.markdown(f"### {m['nome']}")
            st.markdown(f"{badge_stato(m)} &nbsp; :gray[{descrizione_gita(m)} · versione {ultima['n']}, "
                        f"salvata il {data_breve(ultima['data'])} da {ultima['autore']}]")
            k = st.columns(4)
            k[0].metric("Totale", f"{ultima['km_tot']:.1f} km".replace(".", ","))
            k[1].metric("Raccolta", f"{ultima['km_raccolta']:.1f} km".replace(".", ","))
            k[2].metric("Trasferimento", f"{ultima['km_trasferimento']:.1f} km".replace(".", ","))
            k[3].metric("Punti d'interesse", ultima.get("note_mappa", 0))
        b = st.columns(5)
        try:
            if b[0].button("Modifica", icon=":material/edit:", type="primary", width="stretch",
                           disabled=not mod or cestino,
                           help="Apre la gita nell'area di progettazione" if bozza else "Apre la gita nell'editor"):
                if bozza:
                    st.session_state.pagina = "crea"
                    st.session_state.crea_cantiere_iniziale = m.get("cantiere")
                    st.session_state.crea_seleziona = {"id": m["id"], "n": str(time.time())}
                    st.rerun()
                if m.get("cantiere") in flotte["cantieri"] and cantiere_sel not in (TUTTI, m.get("cantiere")):
                    st.session_state.cantiere_sel = m.get("cantiere")
                vai_a("editor", editor_seleziona={"id": m["id"], "n": str(time.time())},
                      **{f"ed_mezzo_{m.get('cantiere')}": TUTTI})
            with b[1].popover("Rinomina", icon=":material/text_fields:", width="stretch", disabled=not mod):
                nuovo = st.text_input("Nuovo nome", value=m["nome"], key=f"rin_{m['id']}")
                if st.button("Salva il nome", type="primary", key=f"rin_ok_{m['id']}"):
                    archivio.rinomina(m["id"], nuovo, utente)
                    salvato(f"Rinominata in \"{nuovo.strip()}\"")
            if b[2].button("Naviga", icon=":material/navigation:", width="stretch", disabled=cestino or bozza,
                           help="Apre la guida come la vedrà l'operatore"):
                st.session_state.guida = (m["id"], versione_operatori(m))
                st.rerun()
            b[3].download_button("GPX", icon=":material/download:", width="stretch", key=f"gpx_{m['id']}",
                                 data=archivio.gpx(m["id"], ultima["n"]), mime="application/gpx+xml",
                                 file_name=f"{m['nome']}_v{ultima['n']}.gpx".replace(" ", "_"))
            if cestino:
                if b[4].button("Ripristina", icon=":material/restore_from_trash:", width="stretch", disabled=not mod):
                    archivio.archivia(m["id"], utente, archiviata=False)
                    salvato(f"Ripristinata: {m['nome']}")
            elif b[4].button("Cestino", icon=":material/delete:", width="stretch", disabled=not mod):
                archivio.archivia(m["id"], utente)
                salvato(f"\"{m['nome']}\" spostata nel cestino")
            if cestino and amministratore:
                with st.popover("Elimina definitivamente", icon=":material/delete_forever:"):
                    st.write(f"**{m['nome']}** e tutte le sue {len(m['versioni'])} versioni saranno cancellate "
                             "e non si potranno recuperare.")
                    if st.button("Sì, elimina definitivamente", type="primary", key=f"del_{m['id']}"):
                        archivio.elimina_definitivamente(m["id"], utente)
                        salvato(f"Eliminata definitivamente: {m['nome']}")
        except (ErroreArchivio, ValueError) as e:
            st.error(str(e))

        t_ver, t_att = st.tabs(["Versioni", "Attività"])
        with t_ver:
            pub = m.get("pubblicata")
            if not bozza and not cestino:
                if pub:
                    st.warning(f"Gli operatori usano la versione {pub['n']}, fissata da {pub['autore']} il "
                               f"{data_breve(pub['data'])}." + (f" La versione {ultima['n']} non la vedono."
                                                                 if pub["n"] != ultima["n"] else ""))
                else:
                    st.caption(f"Gli operatori vedono sempre l'ultima versione (ora la {ultima['n']}).")
            st.dataframe([{"Versione": v["n"], "Operatori": "✓" if not bozza and v["n"] == versione_operatori(m) else "",
                           "Data": data_breve(v["data"]), "Autore": v["autore"], "Nota": v["nota"],
                           "Km": v["km_tot"], "Punti": v["punti"], "Punti d'interesse": v.get("note_mappa", 0)}
                          for v in reversed(m["versioni"])], hide_index=True, width="stretch")
            cv, c1, c2, c3 = st.columns([1.2, 1.4, 1.6, 1.8], vertical_alignment="bottom")
            n = cv.selectbox("Versione", [v["n"] for v in reversed(m["versioni"])], key=f"ver_{m['id']}")
            c1.download_button("Scarica questa versione", data=archivio.gpx(m["id"], n), width="stretch",
                               file_name=f"{m['nome']}_v{n}.gpx".replace(" ", "_"), mime="application/gpx+xml",
                               key=f"gpxv_{m['id']}")
            try:
                if c2.button("Ripristina questa versione", width="stretch", key=f"rip_{m['id']}",
                             disabled=n == ultima["n"] or not mod or cestino):
                    nuova = archivio.ripristina(m["id"], n, utente)
                    salvato(f"La versione {n} è tornata attuale come versione {nuova}")
                if not bozza and not cestino:
                    if pub:
                        if c3.button("Usa sempre l'ultima versione", width="stretch", disabled=not mod,
                                     key=f"sbl_{m['id']}"):
                            archivio.sblocca(m["id"], utente)
                            salvato(f"{m['nome']}: gli operatori vedono l'ultima versione")
                    elif c3.button(f"Fissa la v{n} per gli operatori", width="stretch", disabled=not mod,
                                   key=f"fis_{m['id']}",
                                   help="Gli operatori continuano a usare questa versione finché non la sblocchi"):
                        archivio.pubblica(m["id"], n, utente)
                        salvato(f"{m['nome']}: gli operatori usano la versione {n}")
            except (ErroreArchivio, ValueError) as e:
                st.error(str(e))
        with t_att:
            voci = [(v["data"], v["autore"], f"versione {v['n']}: {v['nota']}") for v in m["versioni"]] + \
                   [(e["data"], e["autore"], e["azione"]) for e in m.get("eventi", [])]
            for data, autore, cosa in sorted(voci, reverse=True):
                st.markdown(f":gray[{data_breve(data)}] **{autore}**: {cosa}")


# ================================================================ editor

def pagina_editor():
    c1, c2 = st.columns([3, 1.3], vertical_alignment="bottom")
    with c1:
        intestazione("Editor", "correggi le gite: punti, trasferimenti, punti d'interesse")
    mezzo = TUTTI
    if cantiere_sel not in (TUTTI, SENZA):
        opz = [TUTTI] + an.mezzi_del_cantiere(flotte, cantiere_sel) + [SENZA]
        mezzo = c2.selectbox("Mezzo", opz, key=f"ed_mezzo_{cantiere_sel}",
                             format_func=lambda k: "Tutti i mezzi" if k == TUTTI else an.etichetta_mezzo(flotte, k))
    gite = sorted([m for m in archivio.elenco() if nel_filtro(m, mezzo)], key=ordine)
    risposta = editor(data=dati_per_editor(gite), data_version=f"{archivio.impronta()}|{cantiere_sel}|{mezzo}",
                      user=utente, msg=st.session_state.get("msg"), height=ALTEZZA_EDITOR,
                      seleziona=st.session_state.get("editor_seleziona"), strade=bool(CHIAVE_STRADE),
                      instradamento=st.session_state.get("instr"), key="editor", default=None)
    gestisci(risposta, cantiere_sel if cantiere_sel not in (TUTTI, SENZA) else None,
             mezzo if mezzo not in (TUTTI, SENZA) else None)


# ================================================================ impostazioni

def pagina_impostazioni():
    intestazione("Impostazioni", "stato dell'archivio e informazioni sul portale")
    for a in avvisi_sistema():
        st.warning(a, icon=":material/warning:")
    st.subheader("Archivio dei dati")
    github = "GitHub" in archivio.descrizione
    st.markdown(f"{':green-badge[Permanente]' if github else ':orange-badge[Cartella locale]'} &nbsp; {archivio.descrizione}")
    if github:
        sc = scadenza_token()
        st.write(f"Il token di accesso scade il **{sc:%d/%m/%Y}**." if sc else
                 "La scadenza del token sarà indicata dopo il primo salvataggio.")
    else:
        st.caption("Se il portale gira su Streamlit Community Cloud, una cartella locale si azzera a ogni riavvio: "
                   "configura la sezione [archivio] nei Secrets come descritto nel README.")
    tutte = archivio.tutte()
    c = st.columns(4)
    c[0].metric("Gite in archivio", len(tutte), border=True)
    c[1].metric("Versioni salvate", sum(len(m["versioni"]) for m in tutte), border=True)
    c[2].metric("Cantieri", len(flotte["cantieri"]), border=True)
    c[3].metric("Utenti", len(utenti_doc["utenti"]), border=True)
    st.subheader("Aggancio alle strade")
    if CHIAVE_STRADE:
        st.markdown(":green-badge[Attivo] &nbsp; Nell'editor, in modalità disegno, i tratti seguono le strade "
                    "(OpenRouteService, profilo mezzi pesanti).")
    else:
        st.markdown(":gray-badge[Non configurato]")
        st.caption("Per disegnare i tratti lungo le strade: registrati gratis su openrouteservice.org, crea una chiave "
                   "(API key) e aggiungi nei Secrets dell'app la sezione `[openrouteservice]` con `chiave = \"...\"`.")
    st.subheader("Accesso")
    st.write(f"Sei collegato come **{chi['nome']}** ({an.RUOLI[ruolo].lower()}).")
    if ADMIN:
        st.caption(f"L'accesso di emergenza '{ADMIN.get('utente')}' è definito nei Secrets dell'app.")


# ================================================================ utenti (solo amministratore)

def scheda_utenti():
    intestazione("Utenti", "accessi, ruoli e cantieri delle persone")
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

def scheda_percorrenze(cant: str):
    st.markdown(f"<div class='titolo-pagina'><b>Gite di {nome_cantiere(cant)}</b>"
                "<span>scegli la gita e avvia la navigazione</span></div>", unsafe_allow_html=True)
    gite = sorted([m for m in archivio.elenco() if m.get("cantiere") == cant], key=lambda m: m["nome"].lower())
    if not gite:
        st.info("In questo cantiere non ci sono ancora gite.")
        return
    cerca = st.text_input("Cerca", placeholder="Cerca una gita per nome", label_visibility="collapsed",
                          key=f"cerca_{cant}")
    if cerca.strip():
        gite = [m for m in gite if cerca.strip().lower() in m["nome"].lower()]
        if not gite:
            st.write("Nessuna gita con questo nome.")
    for m in gite:
        n = versione_operatori(m)
        v = next(x for x in m["versioni"] if x["n"] == n)
        with st.container(border=True):
            st.markdown(f"**{m['nome']}**")
            dettagli = [f"{v['km_tot']:.1f} km".replace(".", ",")]
            if v.get("note_mappa"):
                dettagli.append(f"{v['note_mappa']} punti d'interesse")
            st.caption(", ".join(dettagli))
            c1, c2 = st.columns([3, 1])
            if c1.button("▶  Avvia navigazione", key=f"nav_{m['id']}", type="primary", width="stretch"):
                st.session_state.guida = (m["id"], n)
                st.rerun()
            c2.download_button("GPX", data=archivio.gpx(m["id"], n), key=f"dl_{m['id']}",
                               file_name=f"{m['nome']}.gpx".replace(" ", "_"), mime="application/gpx+xml",
                               width="stretch", help="Per aprire la gita in un'altra app, per esempio OsmAnd")


def scheda_operatore():
    scheda_percorrenze(cantiere_sel)


def scheda_percorrenze_ufficio():
    if cantiere_sel in miei_cantieri:
        scheda_percorrenze(cantiere_sel)
        return
    if not miei_cantieri:
        st.info("Non hai cantieri assegnati.")
        return
    cant = st.selectbox("Cantiere", miei_cantieri, format_func=nome_cantiere, key="perc_cantiere",
                        index=miei_cantieri.index(cantiere_sel) if cantiere_sel in miei_cantieri else 0)
    scheda_percorrenze(cant)


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
    if st.button("🏠  Torna alle gite"):
        st.session_state.pop("guida", None)
        st.rerun()
    risposta = guida(gita={"id": gid, "version": n, "name": m["nome"], "pts": pts, "wpts": wpts},
                     key=f"guida_{gid}_{n}", default=None)
    if risposta and risposta.get("azione") == "chiudi" and risposta.get("nonce") != st.session_state.get("guida_nonce"):
        st.session_state.guida_nonce = risposta["nonce"]
        st.session_state.pop("guida", None)
        st.rerun()


# ================================================================ navigazione

if st.session_state.get("guida"):
    pagina_guida(*st.session_state.guida)
elif st.session_state.get("pagina") == "crea" and miei_cantieri and ruolo != "operatore":
    pagina_crea()
else:
    if ruolo == "operatore":
        PAGINE = {"percorrenze": st.Page(scheda_operatore, title="Percorrenze", icon=":material/navigation:",
                                         url_path="percorrenze", default=True)}
        navigazione = st.navigation(list(PAGINE.values()), position="hidden")
    else:
        PAGINE = {
            "home": st.Page(pagina_home, title="Home", icon=":material/home:", url_path="home", default=True),
            "elenco": st.Page(pagina_elenco, title="Elenco gite", icon=":material/format_list_bulleted:", url_path="gite"),
            "editor": st.Page(pagina_editor, title="Editor", icon=":material/edit_road:", url_path="editor"),
            "nuove": st.Page(scheda_nuove_gite, title="Nuove gite", icon=":material/add_road:", url_path="nuove-gite"),
            "percorrenze": st.Page(scheda_percorrenze_ufficio, title="Percorrenze", icon=":material/navigation:",
                                   url_path="percorrenze"),
            "flotta": st.Page(scheda_flotta, title="Cantieri e mezzi", icon=":material/local_shipping:",
                              url_path="cantieri-e-mezzi"),
            "utenti": st.Page(scheda_utenti, title="Utenti", icon=":material/group:", url_path="utenti"),
            "impostazioni": st.Page(pagina_impostazioni, title="Impostazioni", icon=":material/settings:",
                                    url_path="impostazioni"),
        }
        organizzazione = [PAGINE["flotta"]] + ([PAGINE["utenti"]] if amministratore else []) + [PAGINE["impostazioni"]]
        navigazione = st.navigation({"": [PAGINE["home"]],
                                     "Gite": [PAGINE[k] for k in ("elenco", "editor", "nuove", "percorrenze")],
                                     "Organizzazione": organizzazione})
    barra_laterale_fondo()
    navigazione.run()
