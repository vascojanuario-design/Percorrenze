"""Archivio delle gite.

Struttura dei dati (identica sia su disco sia nel repository GitHub):
    gite/<id>/meta.json   nome della gita e storico delle versioni
    gite/<id>/v001.gpx    una versione per file, mai sovrascritta

I dati possono stare in due posti, scelti in configurazione:
    DepositoLocale  cartella sul server (uso definitivo in azienda)
    DepositoGitHub  repository GitHub privato (uso online, es. Streamlit Community Cloud)
Per passare dal secondo al primo basta clonare il repository nella cartella dati.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import re
import threading
import time
import unicodedata
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

Punto = list  # [lat, lon, tipo] con tipo "r" (raccolta) o "t" (trasferimento)


class Conflitto(Exception):
    """La gita è stata modificata da qualcun altro dopo che la bozza è stata iniziata."""

    def __init__(self, versione_attuale: int):
        super().__init__(versione_attuale)
        self.versione_attuale = versione_attuale


class ErroreArchivio(Exception):
    """Il deposito dei dati non è raggiungibile o ha rifiutato l'operazione."""


# ================================================================ GPX

def _locale(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def leggi_gpx(contenuto: bytes, nome_file: str = "") -> tuple[str, list[Punto]]:
    """Restituisce (nome, punti). Legge tracce (trk) o, in mancanza, rotte (rte)."""
    try:
        radice = ET.fromstring(contenuto)
    except ET.ParseError as e:
        raise ValueError(f"{nome_file}: non è un GPX leggibile ({e})") from None

    punti: list[Punto] = []
    for seg in (el for el in radice.iter() if _locale(el.tag) == "trkseg"):
        tipo = "r"
        for el in seg.iter():
            if _locale(el.tag) == "tipo" and (el.text or "").strip() == "trasferimento":
                tipo = "t"
        for p in (el for el in seg if _locale(el.tag) == "trkpt"):
            punti.append([float(p.get("lat")), float(p.get("lon")), tipo])
    if not punti:
        for p in (el for el in radice.iter() if _locale(el.tag) == "rtept"):
            punti.append([float(p.get("lat")), float(p.get("lon")), "r"])
    if len(punti) < 2:
        raise ValueError(f"{nome_file}: il file non contiene una traccia")

    nome = ""
    for el in radice.iter():
        if _locale(el.tag) == "name" and (el.text or "").strip():
            nome = el.text.strip()
            break
    return nome or Path(nome_file).stem, punti


TIPI_WAYPOINT = {
    "cassonetto": "Cassonetti / raccolta",
    "utenza": "Utenza critica",
    "attenzione": "Attenzione",
    "accesso": "Accesso",
    "nota": "Nota",
}


def leggi_waypoint(contenuto: bytes) -> list[dict]:
    """Punti e note della gita (<wpt> del GPX): [{lat, lon, tipo, testo}]."""
    try:
        radice = ET.fromstring(contenuto)
    except ET.ParseError:
        return []
    out = []
    for w in (el for el in radice if _locale(el.tag) == "wpt"):
        campi = {_locale(c.tag): (c.text or "").strip() for c in w}
        tipo = campi.get("type", "").lower()
        out.append({"lat": float(w.get("lat")), "lon": float(w.get("lon")),
                    "tipo": tipo if tipo in TIPI_WAYPOINT else "nota",
                    "testo": campi.get("desc") or campi.get("name") or ""})
    return pulisci_waypoint(out)


def pulisci_waypoint(waypoint: list[dict] | None) -> list[dict]:
    out = []
    for w in waypoint or []:
        try:
            lat, lon = float(w["lat"]), float(w["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        tipo = w.get("tipo") if w.get("tipo") in TIPI_WAYPOINT else "nota"
        out.append({"lat": round(lat, 6), "lon": round(lon, 6), "tipo": tipo,
                    "testo": str(w.get("testo") or "").strip()[:300]})
    return out


def distanza(a: Punto, b: Punto) -> float:
    r = math.pi / 180
    dl, dn = (b[0] - a[0]) * r, (b[1] - a[1]) * r
    x = math.sin(dl / 2) ** 2 + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin(dn / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(x))


def pulisci(punti: list[Punto]) -> tuple[list[Punto], int]:
    """Toglie i punti doppi consecutivi (meno di 0,5 m). Il tipo del tratto successivo si conserva."""
    out: list[Punto] = []
    rimossi = 0
    for p in punti:
        if out and distanza(out[-1], p) < 0.5:
            out[-1][2] = p[2]
            rimossi += 1
            continue
        out.append([round(p[0], 6), round(p[1], 6), p[2] if p[2] in ("r", "t") else "r"])
    return out, rimossi


def lunghezze(punti: list[Punto]) -> dict:
    racc = trasf = 0.0
    for a, b in zip(punti, punti[1:]):
        d = distanza(a, b)
        if a[2] == "t":
            trasf += d
        else:
            racc += d
    return {"km_tot": round((racc + trasf) / 1000, 2), "km_raccolta": round(racc / 1000, 2),
            "km_trasferimento": round(trasf / 1000, 2)}


def scrivi_gpx(nome: str, punti: list[Punto], descrizione: str = "", waypoint: list[dict] | None = None) -> str:
    """GPX 1.1: punti e note come <wpt>, poi un trkseg per ogni tratto omogeneo con il tipo nelle estensioni."""
    righe = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="Percorsi" xmlns="http://www.topografix.com/GPX/1/1" xmlns:p="urn:percorsi:1">',
        f"  <metadata><name>{escape(nome)}</name><desc>{escape(descrizione)}</desc>"
        f"<time>{_adesso()}</time></metadata>",
    ]
    for w in pulisci_waypoint(waypoint):
        etichetta = w["testo"][:40] or TIPI_WAYPOINT[w["tipo"]]
        righe.append(f'  <wpt lat="{w["lat"]:.6f}" lon="{w["lon"]:.6f}"><name>{escape(etichetta)}</name>'
                     f'<desc>{escape(w["testo"])}</desc><type>{w["tipo"]}</type></wpt>')
    righe.append(f"  <trk><name>{escape(nome)}</name>")
    inizio = 0
    for i in range(1, len(punti)):
        if i == len(punti) - 1 or punti[i][2] != punti[inizio][2]:
            tipo = "trasferimento" if punti[inizio][2] == "t" else "raccolta"
            righe.append(f"    <trkseg><extensions><p:tipo>{tipo}</p:tipo></extensions>")
            for p in punti[inizio:i + 1]:
                righe.append(f'      <trkpt lat="{p[0]:.6f}" lon="{p[1]:.6f}"/>')
            righe.append("    </trkseg>")
            inizio = i
    righe += ["  </trk>", "</gpx>", ""]
    return "\n".join(righe)


def _adesso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _slug(testo: str) -> str:
    t = unicodedata.normalize("NFKD", testo).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:40] or "gita"


# ================================================================ depositi

class DepositoLocale:
    """Cartella su disco. Scritture atomiche e lock su file: sicuro con più utenti sullo stesso server."""

    def __init__(self, cartella: Path):
        from filelock import FileLock

        self.root = Path(cartella)
        (self.root / "gite").mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.root / ".lock"), timeout=30)
        self.descrizione = f"cartella {self.root.resolve()}"

    def aggiorna(self, forza: bool = False) -> None:
        pass

    def leggi(self, path: str) -> bytes | None:
        f = self.root / path
        return f.read_bytes() if f.is_file() else None

    def elenca_meta(self) -> list[str]:
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.glob("gite/*/meta.json"))

    def impronta(self) -> str:
        h = hashlib.sha1()
        for p in self.elenca_meta():
            h.update(self.leggi(p) or b"")
        return h.hexdigest()[:16]

    def scrivi(self, files: dict[str, str], messaggio: str, autore: str) -> None:
        # meta.json per ultimo: finché non è scritto, la nuova versione non esiste per nessuno
        for path in sorted(files, key=lambda p: p.endswith("meta.json")):
            f = self.root / path
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(f.suffix + ".tmp")
            tmp.write_text(files[path], encoding="utf-8")
            os.replace(tmp, f)


class DepositoGitHub:
    """Repository GitHub. Ogni salvataggio è un commit unico con tutti i file della versione.

    Legge l'albero del repository una volta e tiene i file in memoria; ricontrolla GitHub
    ogni 30 secondi per vedere modifiche fatte da fuori. L'aggiornamento del branch non è
    forzato: se qualcuno ha scritto nel frattempo, il salvataggio viene rifiutato invece di
    sovrascrivere.
    """

    INTERVALLO = 30

    def __init__(self, repo: str, token: str, branch: str = "main", api: str = "https://api.github.com"):
        import requests

        if not repo or "/" not in repo:
            raise ErroreArchivio("Repository non indicato: serve nel formato 'utente/nome-repository'")
        if not token:
            raise ErroreArchivio("Manca il token di accesso a GitHub")
        self.api = f"{api.rstrip('/')}/repos/{repo}"
        self.branch = branch
        self.http = requests.Session()
        self.http.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                  "X-GitHub-Api-Version": "2022-11-28"})
        self.lock = threading.RLock()
        self.descrizione = f"GitHub {repo} (branch {branch})"
        self._head = self._tree_sha = None
        self._albero: dict[str, str] = {}      # percorso -> sha del file
        self._contenuti: dict[str, bytes] = {}  # sha -> contenuto
        self._controllato = 0.0
        self.aggiorna(forza=True)

    def _chiama(self, metodo: str, url: str, **kw):
        try:
            r = self.http.request(metodo, self.api + url, timeout=30, **kw)
        except Exception as e:
            raise ErroreArchivio(f"GitHub non raggiungibile: {e}") from None
        if r.status_code >= 400:
            try:
                msg = r.json().get("message", r.text)
            except ValueError:
                msg = r.text
            err = ErroreArchivio(f"GitHub ha risposto {r.status_code}: {msg}")
            err.status = r.status_code
            raise err
        return r.json()

    def aggiorna(self, forza: bool = False) -> None:
        with self.lock:
            if not forza and time.time() - self._controllato < self.INTERVALLO:
                return
            try:
                head = self._chiama("GET", f"/git/ref/heads/{self.branch}")["object"]["sha"]
            except ErroreArchivio as e:
                if getattr(e, "status", 0) in (404, 409):
                    raise ErroreArchivio(
                        f"Il branch '{self.branch}' non esiste o il repository è vuoto. "
                        "Crea il repository dei dati con almeno un file (per esempio un README).") from None
                raise
            self._controllato = time.time()
            if head == self._head:
                return
            tree_sha = self._chiama("GET", f"/git/commits/{head}")["tree"]["sha"]
            albero = self._chiama("GET", f"/git/trees/{tree_sha}", params={"recursive": "1"})
            self._albero = {e["path"]: e["sha"] for e in albero["tree"] if e["type"] == "blob"}
            self._head, self._tree_sha = head, tree_sha

    def leggi(self, path: str) -> bytes | None:
        self.aggiorna()
        sha = self._albero.get(path)
        if sha is None:
            return None
        if sha not in self._contenuti:
            blob = self._chiama("GET", f"/git/blobs/{sha}")
            self._contenuti[sha] = base64.b64decode(blob["content"])
        return self._contenuti[sha]

    def elenca_meta(self) -> list[str]:
        self.aggiorna()
        return sorted(p for p in self._albero if re.fullmatch(r"gite/[a-z0-9-]+/meta\.json", p))

    def impronta(self) -> str:
        self.aggiorna()
        return (self._head or "")[:16]

    @staticmethod
    def _sha_git(dati: bytes) -> str:
        return hashlib.sha1(b"blob %d\0" % len(dati) + dati).hexdigest()

    def scrivi(self, files: dict[str, str], messaggio: str, autore: str) -> None:
        with self.lock:
            voci = [{"path": p, "mode": "100644", "type": "blob", "content": c} for p, c in files.items()]
            tree = self._chiama("POST", "/git/trees", json={"base_tree": self._tree_sha, "tree": voci})["sha"]
            firma = {"name": autore or "Percorsi", "email": "percorsi@users.noreply.github.com", "date": _adesso()}
            commit = self._chiama("POST", "/git/commits", json={"message": messaggio, "tree": tree,
                                                               "parents": [self._head], "author": firma})["sha"]
            try:
                self._chiama("PATCH", f"/git/refs/heads/{self.branch}", json={"sha": commit, "force": False})
            except ErroreArchivio as e:
                if getattr(e, "status", 0) == 422:
                    self.aggiorna(forza=True)
                    raise ErroreArchivio("Il repository dei dati è stato modificato nel frattempo. Riprova.") from None
                raise
            for p, c in files.items():
                dati = c.encode("utf-8")
                sha = self._sha_git(dati)
                self._albero[p] = sha
                self._contenuti[sha] = dati
            self._head, self._tree_sha = commit, tree


# ================================================================ archivio

class Archivio:
    def __init__(self, deposito: DepositoLocale | DepositoGitHub):
        self.d = deposito

    @property
    def descrizione(self) -> str:
        return self.d.descrizione

    # --- lettura

    @staticmethod
    def _cartella(gid: str) -> str:
        if not re.fullmatch(r"[a-z0-9-]+", gid or ""):
            raise ValueError("Identificativo gita non valido")
        return f"gite/{gid}"

    def meta(self, gid: str) -> dict:
        dati = self.d.leggi(f"{self._cartella(gid)}/meta.json")
        if dati is None:
            raise FileNotFoundError(f"La gita {gid} non esiste")
        return json.loads(dati)

    def elenco(self, archiviate: bool = False) -> list[dict]:
        out = [json.loads(self.d.leggi(p)) for p in self.d.elenca_meta()]
        out = [m for m in out if bool(m.get("archiviata")) == archiviate]
        return sorted(out, key=lambda m: m["nome"].lower())

    def punti(self, gid: str, n: int | None = None) -> list[Punto]:
        m = self.meta(gid)
        v = m["versioni"][-1] if n is None else next(v for v in m["versioni"] if v["n"] == n)
        _, pts = leggi_gpx(self.d.leggi(f"{self._cartella(gid)}/{v['file']}"), v["file"])
        return pulisci(pts)[0]

    def contenuto(self, gid: str, n: int | None = None) -> tuple[list[Punto], list[dict]]:
        """Percorso e punti/note di una versione (l'ultima se n è None)."""
        m = self.meta(gid)
        v = m["versioni"][-1] if n is None else next(v for v in m["versioni"] if v["n"] == n)
        dati = self.d.leggi(f"{self._cartella(gid)}/{v['file']}")
        _, pts = leggi_gpx(dati, v["file"])
        return pulisci(pts)[0], leggi_waypoint(dati)

    def gpx(self, gid: str, n: int) -> str:
        v = next(v for v in self.meta(gid)["versioni"] if v["n"] == n)
        return self.d.leggi(f"{self._cartella(gid)}/{v['file']}").decode("utf-8")

    def impronta(self) -> str:
        """Cambia ogni volta che una gita viene creata, modificata o archiviata."""
        return self.d.impronta()

    def vuoto(self) -> bool:
        return not self.d.elenca_meta()

    # --- scrittura

    def _nuova_versione(self, m: dict, punti: list[Punto], autore: str, nota: str, nonce: str | None,
                        waypoint: list[dict] | None = None) -> dict:
        n = m["versioni"][-1]["n"] + 1 if m["versioni"] else 1
        file = f"v{n:03d}.gpx"
        v = {"n": n, "file": file, "data": _adesso(), "autore": autore, "nota": nota, "nome": m["nome"],
             "punti": len(punti), "note_mappa": len(pulisci_waypoint(waypoint)), **lunghezze(punti)}
        if nonce:
            v["invio"] = nonce
        m["versioni"].append(v)
        cartella = self._cartella(m["id"])
        self.d.scrivi({f"{cartella}/{file}": scrivi_gpx(m["nome"], punti, f"Versione {n}: {nota}", waypoint),
                       f"{cartella}/meta.json": json.dumps(m, ensure_ascii=False, indent=2)},
                      f"{m['nome']}: versione {n} - {nota}", autore)
        return v

    def crea(self, nome: str, punti: list[Punto], autore: str, nota: str, nonce: str | None = None,
             cantiere: str | None = None, mezzo: str | None = None, waypoint: list[dict] | None = None) -> str:
        punti, _ = pulisci(punti)
        if len(punti) < 2:
            raise ValueError("Una gita deve avere almeno due punti")
        with self.d.lock:
            self.d.aggiorna(forza=True)
            gid = f"{_slug(nome)}-{uuid.uuid4().hex[:6]}"
            m = {"id": gid, "nome": nome.strip() or "Gita senza nome", "creata": _adesso(), "creata_da": autore,
                 "archiviata": False, "cantiere": cantiere, "mezzo": mezzo, "versioni": []}
            self._nuova_versione(m, punti, autore, nota, nonce, waypoint)
        return gid

    def salva(self, gid: str, punti: list[Punto], autore: str, nota: str, base: int, nome: str | None = None,
              nonce: str | None = None, waypoint: list[dict] | None = None) -> int:
        """Salva una nuova versione. Rifiuta se nel frattempo qualcuno ha inviato una versione più recente."""
        punti, _ = pulisci(punti)
        if len(punti) < 2:
            raise ValueError("Una gita deve avere almeno due punti")
        with self.d.lock:
            self.d.aggiorna(forza=True)
            m = self.meta(gid)
            attuale = m["versioni"][-1]["n"]
            if base != attuale:
                raise Conflitto(attuale)
            if nome and nome.strip():
                m["nome"] = nome.strip()
            return self._nuova_versione(m, punti, autore, nota, nonce, waypoint)["n"]

    def ripristina(self, gid: str, n: int, autore: str) -> int:
        with self.d.lock:
            self.d.aggiorna(forza=True)
            punti, waypoint = self.contenuto(gid, n)
            m = self.meta(gid)
            return self._nuova_versione(m, punti, autore, f"Ripristinata la versione {n}", None, waypoint)["n"]

    def archivia(self, gid: str, autore: str, archiviata: bool = True) -> None:
        with self.d.lock:
            self.d.aggiorna(forza=True)
            m = self.meta(gid)
            m["archiviata"] = archiviata
            azione = "archiviata" if archiviata else "riattivata"
            m.setdefault("eventi", []).append({"data": _adesso(), "autore": autore, "azione": azione})
            self.d.scrivi({f"{self._cartella(gid)}/meta.json": json.dumps(m, ensure_ascii=False, indent=2)},
                          f"{m['nome']}: {azione}", autore)

    def assegna(self, gid: str, autore: str, **campi) -> bool:
        """Aggiorna cantiere, mezzo, turno, giorni o numero della gita. Non crea una nuova versione del percorso."""
        consentiti = {"cantiere", "mezzo", "turno", "giorni", "numero"}
        with self.d.lock:
            self.d.aggiorna(forza=True)
            m = self.meta(gid)
            cambi = {k: v for k, v in campi.items() if k in consentiti and m.get(k) != v}
            if not cambi:
                return False
            m.update(cambi)
            m.setdefault("eventi", []).append({"data": _adesso(), "autore": autore, "azione": "assegnazione aggiornata",
                                              "dettagli": cambi})
            self.d.scrivi({f"{self._cartella(gid)}/meta.json": json.dumps(m, ensure_ascii=False, indent=2)},
                          f"{m['nome']}: assegnazione aggiornata", autore)
            return True

    def pubblica(self, gid: str, n: int, autore: str) -> None:
        """Approva la versione n per la strada: è quella che vedranno gli operatori."""
        with self.d.lock:
            self.d.aggiorna(forza=True)
            m = self.meta(gid)
            if not any(v["n"] == n for v in m["versioni"]):
                raise ValueError(f"La versione {n} non esiste")
            m["pubblicata"] = {"n": n, "data": _adesso(), "autore": autore}
            m.setdefault("eventi", []).append({"data": _adesso(), "autore": autore,
                                              "azione": f"pubblicata la versione {n}"})
            self.d.scrivi({f"{self._cartella(gid)}/meta.json": json.dumps(m, ensure_ascii=False, indent=2)},
                          f"{m['nome']}: pubblicata la versione {n}", autore)

    # --- anagrafica condivisa (utenti, cantieri, mezzi)

    def leggi_doc(self, nome: str, predefinito: dict) -> dict:
        dati = self.d.leggi(f"anagrafica/{nome}.json")
        return json.loads(dati) if dati else json.loads(json.dumps(predefinito))

    def modifica_doc(self, nome: str, predefinito: dict, funzione, messaggio: str, autore: str):
        """Legge il documento aggiornato, applica la modifica e lo salva, tutto sotto lock.
        Se la funzione solleva un'eccezione non viene scritto nulla."""
        with self.d.lock:
            self.d.aggiorna(forza=True)
            doc = self.leggi_doc(nome, predefinito)
            risultato = funzione(doc)
            self.d.scrivi({f"anagrafica/{nome}.json": json.dumps(doc, ensure_ascii=False, indent=2)}, messaggio, autore)
            return risultato

    # --- esportazione e prima importazione

    def zip_ultime(self, gite: list[dict] | None = None) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for m in (self.elenco() if gite is None else gite):
                v = m["versioni"][-1]
                z.writestr(f"{_slug(m['nome'])}_v{v['n']}.gpx", self.gpx(m["id"], v["n"]))
        return buf.getvalue()

    def semina(self, cartella: Path, autore: str = "importazione iniziale") -> int:
        """Importa i GPX di una cartella se l'archivio è vuoto. Restituisce quante gite ha creato."""
        if not self.vuoto() or not Path(cartella).is_dir():
            return 0
        n = 0
        for f in sorted(Path(cartella).glob("*.gpx")):
            nome, pts = leggi_gpx(f.read_bytes(), f.name)
            pts, rimossi = pulisci(pts)
            self.crea(nome, pts, autore, f"Importata da {f.name}" + (f", rimossi {rimossi} punti doppi" if rimossi else ""))
            n += 1
        return n


def apri(config: dict | None, cartella_predefinita: Path) -> Archivio:
    """Sceglie il deposito in base alla configurazione ([archivio] nei secrets di Streamlit)."""
    config = config or {}
    if config.get("tipo") == "github":
        return Archivio(DepositoGitHub(config.get("repo", ""), config.get("token", ""),
                                       config.get("branch", "main"), config.get("api", "https://api.github.com")))
    return Archivio(DepositoLocale(Path(config.get("cartella") or cartella_predefinita)))
