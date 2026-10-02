"""Portale percorsi: correzione condivisa delle gite di raccolta.

Avvio:  streamlit run app.py
Cartella dati: variabile d'ambiente PERCORSI_DATA_DIR (predefinita: ./dati)
"""
import os
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from archivio import Archivio, Conflitto, leggi_gpx, pulisci

BASE = Path(__file__).parent
DATA_DIR = Path(os.environ.get("PERCORSI_DATA_DIR", BASE / "dati"))
HEADER_UTENTE = os.environ.get("PERCORSI_HEADER_UTENTE", "X-Remote-User")
ALTEZZA_EDITOR = 820

st.set_page_config(page_title="Percorsi", page_icon="🗺️", layout="wide")
st.markdown(
    "<style>.block-container{padding-top:3.2rem;padding-bottom:1rem;max-width:100%}"
    "iframe[title='editor_percorsi']{border:1px solid #D3DAD8;border-radius:8px}</style>",
    unsafe_allow_html=True,
)

editor = components.declare_component("editor_percorsi", path=str(BASE / "editor"))


@st.cache_resource
def apri_archivio() -> Archivio:
    a = Archivio(DATA_DIR)
    a.semina(BASE / "seed")
    return a


archivio = apri_archivio()


@st.cache_data(show_spinner=False)
def dati_editor(impronta: str) -> list[dict]:
    """Ultima versione di ogni gita attiva. Ricalcolata solo quando l'archivio cambia."""
    out = []
    for m in archivio.elenco():
        ultima = m["versioni"][-1]
        out.append({"id": m["id"], "name": m["nome"], "version": ultima["n"], "invio": ultima.get("invio"),
                    "pts": archivio.punti(m["id"])})
    return out


def data_breve(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")


def avviso(testo: str, ok: bool = True, nonce: str | None = None, local_id: str | None = None,
           gita_id: str | None = None) -> None:
    """Messaggio mostrato sia da Streamlit sia dentro l'editor."""
    st.session_state.msg = {"nonce": nonce or str(datetime.now().timestamp()), "ok": ok, "text": testo,
                            "local_id": local_id, "gita_id": gita_id}
    st.session_state.avvisi = st.session_state.get("avvisi", []) + [(testo, ok)]


# ---------------------------------------------------------------- utente

utente_proxy = st.context.headers.get(HEADER_UTENTE)

with st.sidebar:
    st.title("Percorsi")
    if utente_proxy:
        st.session_state.utente = utente_proxy
        st.caption(f"Connesso come **{utente_proxy}**")
    else:
        st.text_input("Il tuo nome", key="utente", placeholder="Nome e cognome",
                      help="Compare nello storico accanto alle versioni che invii.")
    utente = (st.session_state.get("utente") or "").strip()

    st.divider()
    st.subheader("Aggiungi gite")
    chiave_upload = f"upload_{st.session_state.get('upload_n', 0)}"
    nuovi = st.file_uploader("File GPX", type=["gpx"], accept_multiple_files=True, key=chiave_upload,
                             label_visibility="collapsed")
    if nuovi and st.button("Importa", type="primary", width="stretch"):
        if not utente:
            st.error("Scrivi il tuo nome prima di importare.")
        else:
            for f in nuovi:
                try:
                    nome, pts = leggi_gpx(f.getvalue(), f.name)
                    pts, rimossi = pulisci(pts)
                    archivio.crea(nome, pts, utente,
                                  f"Importata da {f.name}" + (f", rimossi {rimossi} punti doppi" if rimossi else ""))
                    avviso(f"Importata: {nome}")
                except ValueError as e:
                    avviso(str(e), ok=False)
            st.session_state.upload_n = st.session_state.get("upload_n", 0) + 1
            st.rerun()

    st.divider()
    st.download_button("Scarica tutte le gite (ZIP)", data=archivio.zip_ultime(),
                       file_name=f"gite_{datetime.now():%Y%m%d}.zip", mime="application/zip",
                       width="stretch")
    st.caption(f"Archivio: `{DATA_DIR.resolve()}`")

for testo, ok in st.session_state.pop("avvisi", []):
    st.toast(testo, icon="✅" if ok else "⚠️")

# ---------------------------------------------------------------- editor e storico

scheda_editor, scheda_storico = st.tabs(["Editor", "Storico versioni"])

with scheda_editor:
    if not utente:
        st.info("Scrivi il tuo nome nella barra laterale: serve per inviare le correzioni.")
    impronta = archivio.impronta()
    risposta = editor(data=dati_editor(impronta), data_version=impronta, user=utente,
                      msg=st.session_state.get("msg"), height=ALTEZZA_EDITOR, key="editor", default=None)

    if risposta and risposta.get("nonce") != st.session_state.get("ultimo_nonce"):
        st.session_state.ultimo_nonce = risposta["nonce"]
        azione, gid, nonce = risposta.get("action"), risposta.get("gita_id"), risposta["nonce"]
        try:
            if not utente:
                avviso("Scrivi il tuo nome nella barra laterale prima di inviare.", ok=False, nonce=nonce)
            elif azione == "save":
                n = archivio.salva(gid, risposta["pts"], utente, risposta.get("note") or "Correzioni",
                                   base=int(risposta["base"]), nome=risposta.get("name"), nonce=nonce)
                avviso(f"Salvata la versione {n} di {risposta.get('name')}", nonce=nonce)
            elif azione == "create":
                archivio.crea(risposta.get("name") or "Gita senza nome", risposta["pts"], utente,
                              risposta.get("note") or "Creata dall'editor", nonce=nonce)
                avviso(f"Creata la gita {risposta.get('name')}", nonce=nonce, local_id=risposta.get("local_id"))
            elif azione == "archive":
                archivio.archivia(gid, utente)
                avviso("Gita archiviata. Puoi riattivarla dallo storico.", nonce=nonce)
        except Conflitto as c:
            avviso(f"Non salvata: nel frattempo un collega ha inviato la versione {c.versione_attuale}. "
                   "La tua bozza è conservata come copia \"(tua bozza)\": confrontala con la nuova versione "
                   "e riporta lì le correzioni.", ok=False, nonce=nonce, gita_id=gid)
        except (ValueError, KeyError, FileNotFoundError) as e:
            avviso(f"Non salvata: {e}", ok=False, nonce=nonce)
        st.rerun()

with scheda_storico:
    mostra_archiviate = st.toggle("Mostra le gite archiviate")
    gite = archivio.elenco(archiviate=mostra_archiviate)
    if not gite:
        st.write("Nessuna gita archiviata." if mostra_archiviate else "Nessuna gita nell'archivio.")
    else:
        m = st.selectbox("Gita", gite, format_func=lambda g: g["nome"])
        ultima = m["versioni"][-1]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Versione attuale", ultima["n"])
        c2.metric("Totale", f"{ultima['km_tot']:.1f} km".replace(".", ","))
        c3.metric("Raccolta", f"{ultima['km_raccolta']:.1f} km".replace(".", ","))
        c4.metric("Trasferimento", f"{ultima['km_trasferimento']:.1f} km".replace(".", ","))

        st.dataframe(
            [{"Versione": v["n"], "Data": data_breve(v["data"]), "Autore": v["autore"], "Nota": v["nota"],
              "Km": v["km_tot"], "Punti": v["punti"]} for v in reversed(m["versioni"])],
            hide_index=True, width="stretch",
        )

        col_v, col_dl, col_rip = st.columns([2, 2, 2], vertical_alignment="bottom")
        n = col_v.selectbox("Versione", [v["n"] for v in reversed(m["versioni"])], key=f"ver_{m['id']}")
        col_dl.download_button("Scarica GPX", data=archivio.gpx(m["id"], n),
                               file_name=f"{m['nome']}_v{n}.gpx".replace(" ", "_"),
                               mime="application/gpx+xml", width="stretch")
        if mostra_archiviate:
            if col_rip.button("Riattiva la gita", width="stretch"):
                archivio.archivia(m["id"], utente or "sconosciuto", archiviata=False)
                avviso(f"Riattivata: {m['nome']}")
                st.rerun()
        elif col_rip.button("Ripristina questa versione", width="stretch",
                            disabled=n == ultima["n"] or not utente,
                            help=None if utente else "Scrivi il tuo nome nella barra laterale"):
            nuova = archivio.ripristina(m["id"], n, utente)
            avviso(f"La versione {n} è tornata attuale come versione {nuova}")
            st.rerun()

        for e in reversed(m.get("eventi", [])):
            st.caption(f"{data_breve(e['data'])}: {e['azione']} da {e['autore']}")
