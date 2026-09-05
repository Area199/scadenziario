"""
Scadenze & Spese — gestione condivisa delle uscite di casa.
Streamlit + Supabase (REST).
"""

import calendar
import uuid
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dateutil.relativedelta import relativedelta
from supabase import Client, create_client

# ----------------------------------------------------------------------------
# Configurazione
# ----------------------------------------------------------------------------

ORIZZONTE_MESI = 6          # quanti mesi mostra il riepilogo e genera le ricorrenti
GIORNI_ALERT = 20           # soglia di alert richiesta
GIORNI_COPERTURA = 30       # finestra per il controllo saldo/domiciliazioni

C = {
    "bg": "#000000",
    "surface": "#121216",
    "line": "#2A2A31",
    "text": "#ECEAE6",
    "muted": "#8B8B93",
    "rosso": "#FF4B3E",
    "ambra": "#FFB020",
    "verde": "#5FD3A6",
    "domic": "#5B8DEF",
}

CATEGORIE = [
    "Casa", "Utenze", "Auto", "Assicurazioni", "Tasse", "Salute",
    "Scuola", "Finanziamenti", "Abbonamenti", "Altro",
]

st.set_page_config(page_title="Scadenze & Spese", page_icon="💸", layout="wide")

st.markdown(
    f"""
    <style>
      .stApp, [data-testid="stHeader"], [data-testid="stSidebar"],
      [data-testid="stBottomBlockContainer"] {{ background-color: {C['bg']}; }}
      [data-testid="stHeader"] {{ border-bottom: 1px solid {C['line']}; }}
      html, body, [class*="css"] {{ color: {C['text']}; }}
      .block-container {{ padding-top: 2.2rem; max-width: 1150px; }}

      .titolo {{ font-size: 1.45rem; font-weight: 600; letter-spacing: -.02em;
                 margin: 0 0 .15rem 0; }}
      .sottotitolo {{ color: {C['muted']}; font-size: .86rem; margin-bottom: 1.4rem; }}
      .sezione {{ font-size: 1.02rem; font-weight: 600; margin: 1.6rem 0 .7rem 0; }}

      .voce {{ background: {C['surface']}; border: 1px solid {C['line']};
               border-left: 3px solid {C['muted']}; border-radius: 8px;
               padding: .7rem .9rem; margin-bottom: .45rem; }}
      .voce .riga1 {{ display: flex; justify-content: space-between; gap: 1rem;
                      align-items: baseline; }}
      .voce .desc {{ font-weight: 600; font-size: .98rem; }}
      .voce .imp {{ font-variant-numeric: tabular-nums; font-weight: 600;
                    font-size: 1.02rem; white-space: nowrap; }}
      .voce .riga2 {{ color: {C['muted']}; font-size: .8rem; margin-top: .2rem; }}
      .voce .accant {{ color: {C['muted']}; font-size: .78rem; margin-top: .45rem;
                       border-top: 1px dashed {C['line']}; padding-top: .4rem;
                       font-variant-numeric: tabular-nums; }}
      .tag {{ border: 1px solid currentColor; border-radius: 4px; padding: 0 .35rem;
              font-size: .7rem; }}

      .kpi {{ background: {C['surface']}; border: 1px solid {C['line']};
              border-radius: 8px; padding: .85rem 1rem; height: 100%; }}
      .kpi .lab {{ color: {C['muted']}; font-size: .78rem; }}
      .kpi .val {{ font-size: 1.5rem; font-weight: 600; font-variant-numeric: tabular-nums;
                   letter-spacing: -.02em; margin-top: .1rem; }}

      .stButton > button {{ background: {C['surface']}; color: {C['text']};
                            border: 1px solid {C['line']}; border-radius: 7px; }}
      .stButton > button:hover {{ border-color: {C['verde']}; color: {C['verde']}; }}
      [data-testid="stMetricValue"] {{ font-size: 1.4rem; }}
      div[data-baseweb="tab-list"] {{ background: transparent; gap: .3rem; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ----------------------------------------------------------------------------
# Utilità
# ----------------------------------------------------------------------------

def eur(x: float) -> str:
    s = f"{float(x):,.2f}"
    return "€ " + s.replace(",", "§").replace(".", ",").replace("§", ".")


def giorni_a(d: date) -> int:
    return (d - date.today()).days


def stato_voce(d: date):
    """Etichetta + colore in base all'urgenza."""
    g = giorni_a(d)
    if g < 0:
        return f"scaduta da {abs(g)} g", C["rosso"]
    if g == 0:
        return "scade oggi", C["rosso"]
    if g <= 7:
        return f"tra {g} g", C["rosso"]
    if g <= GIORNI_ALERT:
        return f"tra {g} g", C["ambra"]
    return f"tra {g} g", C["muted"]


def accantonamento(importo: float, d: date):
    """Quanto serve mettere da parte al giorno / settimana / mese."""
    g = max(giorni_a(d), 1)
    return importo / g, importo * 7 / g, importo * 30.44 / g


def giorno_valido(anno: int, mese: int, giorno: int) -> date:
    return date(anno, mese, min(giorno, calendar.monthrange(anno, mese)[1]))


def mese_label(d: date) -> str:
    nomi = ["gen", "feb", "mar", "apr", "mag", "giu",
            "lug", "ago", "set", "ott", "nov", "dic"]
    return f"{nomi[d.month - 1]} {d.year}"


# ----------------------------------------------------------------------------
# Accesso
# ----------------------------------------------------------------------------

def login() -> bool:
    if st.session_state.get("utente"):
        return True

    st.markdown('<div class="titolo">Scadenze & Spese</div>', unsafe_allow_html=True)
    st.markdown('<div class="sottotitolo">Inserisci la password per entrare.</div>',
                unsafe_allow_html=True)

    col, _ = st.columns([1, 2])
    with col:
        with st.form("login"):
            pwd = st.text_input("Password", type="password", label_visibility="collapsed",
                                placeholder="Password")
            entra = st.form_submit_button("Entra")
        if entra:
            utenti = dict(st.secrets.get("auth", {}))
            for nome, p in utenti.items():
                if pwd and pwd == p:
                    st.session_state.utente = nome
                    st.rerun()
            st.error("Password non riconosciuta. Riprova.")
    return False


# ----------------------------------------------------------------------------
# Database
# ----------------------------------------------------------------------------

def _cerca_secret(*nomi):
    """Cerca una chiave in cima ai secrets o dentro una sezione [supabase]."""
    sezione = {}
    if "supabase" in st.secrets:
        sezione = dict(st.secrets["supabase"])
    for nome in nomi:
        for fonte in (st.secrets, sezione):
            for k in list(fonte.keys()):
                if k.lower() == nome.lower():
                    return fonte[k]
    return None


@st.cache_resource
def db() -> Client:
    url = _cerca_secret("SUPABASE_URL", "url", "supabase_url")
    key = _cerca_secret("SUPABASE_KEY", "key", "supabase_key",
                        "SUPABASE_ANON_KEY", "anon_key", "supabase_anon_key")
    if not url or not key:
        trovate = ", ".join(k for k in st.secrets.keys() if k != "auth") or "nessuna"
        st.error(
            "Configurazione Supabase incompleta.\n\n"
            f"Righe trovate nei secrets: {trovate}.\n\n"
            "Servono l'indirizzo del progetto e la chiave anon, in cima ai secrets "
            "oppure in una sezione [supabase]."
        )
        st.stop()
    return create_client(str(url), str(key))


COLONNE_SPESE = ["id", "descrizione", "categoria", "importo", "data_scadenza", "tipo",
                 "gruppo_id", "rata_num", "rata_tot", "note", "pagata", "data_pagamento",
                 "origine", "creata_da"]


def carica_spese() -> pd.DataFrame:
    res = db().table("casa_spese").select("*").order("data_scadenza").execute()
    df = pd.DataFrame(res.data)
    if df.empty:
        return pd.DataFrame(columns=COLONNE_SPESE)
    df["data_scadenza"] = pd.to_datetime(df["data_scadenza"]).dt.date
    df["data_pagamento"] = pd.to_datetime(df["data_pagamento"], errors="coerce")
    df["importo"] = pd.to_numeric(df["importo"])
    return df


def carica_ricorrenti() -> pd.DataFrame:
    res = db().table("casa_ricorrenti").select("*").order("descrizione").execute()
    df = pd.DataFrame(res.data)
    if df.empty:
        return pd.DataFrame(columns=["id", "descrizione", "categoria", "importo",
                                     "giorno_mese", "ogni_mesi", "tipo", "data_inizio",
                                     "attiva"])
    df["data_inizio"] = pd.to_datetime(df["data_inizio"]).dt.date
    df["importo"] = pd.to_numeric(df["importo"])
    return df


def leggi_saldo() -> float:
    res = db().table("casa_conto").select("saldo").eq("id", 1).execute()
    return float(res.data[0]["saldo"]) if res.data else 0.0


def scrivi_saldo(valore: float):
    db().table("casa_conto").upsert({"id": 1, "saldo": valore,
                                "aggiornato_at": "now()"}).execute()


def inserisci_spese(righe: list):
    if righe:
        db().table("casa_spese").insert(righe).execute()


def segna_pagata(spesa_id: str, pagata: bool = True):
    db().table("casa_spese").update({
        "pagata": pagata,
        "data_pagamento": date.today().isoformat() if pagata else None,
    }).eq("id", spesa_id).execute()


def elimina_spesa(spesa_id: str):
    db().table("casa_spese").delete().eq("id", spesa_id).execute()


def genera_da_ricorrenti():
    """Crea le scadenze delle spese ricorrenti fino all'orizzonte, senza duplicati."""
    ric = carica_ricorrenti()
    if ric.empty:
        return 0
    spese = carica_spese()
    esistenti = set()
    if not spese.empty:
        esistenti = {(str(g), d) for g, d in
                     zip(spese["gruppo_id"], spese["data_scadenza"])}

    oggi = date.today()
    limite = oggi + relativedelta(months=ORIZZONTE_MESI)
    nuove = []

    for _, r in ric.iterrows():
        if not r["attiva"]:
            continue
        inizio = r["data_inizio"]
        cursore = max(inizio.replace(day=1), oggi.replace(day=1))
        while cursore <= limite:
            diff = (cursore.year - inizio.year) * 12 + (cursore.month - inizio.month)
            if diff >= 0 and diff % int(r["ogni_mesi"]) == 0:
                d = giorno_valido(cursore.year, cursore.month, int(r["giorno_mese"]))
                if d >= inizio and (str(r["id"]), d) not in esistenti:
                    nuove.append({
                        "descrizione": r["descrizione"],
                        "categoria": r["categoria"],
                        "importo": float(r["importo"]),
                        "data_scadenza": d.isoformat(),
                        "tipo": r["tipo"],
                        "gruppo_id": str(r["id"]),
                        "origine": "ricorrente",
                        "creata_da": st.session_state.get("utente", ""),
                    })
            cursore += relativedelta(months=1)

    inserisci_spese(nuove)
    return len(nuove)


# ----------------------------------------------------------------------------
# Componenti
# ----------------------------------------------------------------------------

def riga_voce(row, mostra_accantonamento=True, archivio=False):
    domic = row["tipo"] == "domiciliazione"
    if archivio:
        etichetta, colore = "pagata", C["verde"]
    else:
        etichetta, colore = stato_voce(row["data_scadenza"])
        if domic and giorni_a(row["data_scadenza"]) > GIORNI_ALERT:
            colore = C["domic"]

    rata = ""
    if pd.notna(row.get("rata_tot")) and row.get("rata_tot"):
        rata = f" · rata {int(row['rata_num'])}/{int(row['rata_tot'])}"

    tipo_tag = (f'<span class="tag" style="color:{C["domic"]}">domiciliazione</span>'
                if domic else "")

    acc_html = ""
    if mostra_accantonamento and not archivio:
        g, s, m = accantonamento(row["importo"], row["data_scadenza"])
        acc_html = (f'<div class="accant">Da accantonare · {eur(g)} al giorno '
                    f'· {eur(s)} a settimana · {eur(m)} al mese</div>')

    data_txt = row["data_scadenza"].strftime("%d/%m/%Y")
    cat = row.get("categoria") or "—"

    c1, c2 = st.columns([6, 1.5])
    with c1:
        st.markdown(
            f"""<div class="voce" style="border-left-color:{colore}">
              <div class="riga1">
                <span class="desc">{row['descrizione']}</span>
                <span class="imp">{eur(row['importo'])}</span>
              </div>
              <div class="riga2">{data_txt} · <span style="color:{colore}">{etichetta}</span>
                 · {cat}{rata} {tipo_tag}</div>
              {acc_html}
            </div>""",
            unsafe_allow_html=True,
        )
    with c2:
        if archivio:
            if st.button("Riapri", key=f"riapri_{row['id']}", use_container_width=True):
                segna_pagata(row["id"], False)
                st.rerun()
        else:
            if st.button("Pagata", key=f"pay_{row['id']}", use_container_width=True):
                segna_pagata(row["id"], True)
                st.rerun()
            if st.button("Elimina", key=f"del_{row['id']}", use_container_width=True):
                elimina_spesa(row["id"])
                st.rerun()


def kpi(label: str, valore: str, colore: str = None):
    col = colore or C["text"]
    st.markdown(
        f'<div class="kpi"><div class="lab">{label}</div>'
        f'<div class="val" style="color:{col}">{valore}</div></div>',
        unsafe_allow_html=True,
    )


def grafico_sei_mesi(attive: pd.DataFrame):
    oggi = date.today()
    mesi = [(oggi.replace(day=1) + relativedelta(months=i)) for i in range(ORIZZONTE_MESI)]
    etichette = [mese_label(m) for m in mesi]

    def somma(mese, tipo):
        if attive.empty:
            return 0.0
        m = attive[
            (attive["data_scadenza"] >= mese)
            & (attive["data_scadenza"] < mese + relativedelta(months=1))
            & (attive["tipo"] == tipo)
        ]
        return float(m["importo"].sum())

    pagamenti = [somma(m, "pagamento") for m in mesi]
    domiciliazioni = [somma(m, "domiciliazione") for m in mesi]
    totali = [p + d for p, d in zip(pagamenti, domiciliazioni)]

    fig = go.Figure()
    fig.add_bar(x=etichette, y=pagamenti, name="Da pagare",
                marker_color=C["ambra"], hovertemplate="%{y:.2f} €<extra>Da pagare</extra>")
    fig.add_bar(x=etichette, y=domiciliazioni, name="Domiciliazioni",
                marker_color=C["domic"], hovertemplate="%{y:.2f} €<extra>Domiciliazioni</extra>")
    fig.add_scatter(x=etichette, y=[t * 1.04 for t in totali], mode="text",
                    text=[eur(t) if t else "" for t in totali],
                    textposition="top center", showlegend=False,
                    textfont=dict(color=C["text"], size=12), hoverinfo="skip")

    fig.update_layout(
        barmode="stack",
        height=300,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=C["text"], size=12),
        legend=dict(orientation="h", y=1.16, x=0, bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(showgrid=False, linecolor=C["line"]),
        yaxis=dict(gridcolor=C["line"], zerolinecolor=C["line"], tickformat=",.0f"),
        bargap=0.45,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ----------------------------------------------------------------------------
# Pagine
# ----------------------------------------------------------------------------

def pagina_scadenze(spese: pd.DataFrame, saldo: float):
    oggi = date.today()
    attive = spese[~spese["pagata"]].copy() if not spese.empty else spese
    limite = oggi + relativedelta(months=ORIZZONTE_MESI)

    # --- Riepilogo visivo 6 mesi ---
    st.markdown('<div class="sezione">Prossimi sei mesi</div>', unsafe_allow_html=True)
    grafico_sei_mesi(attive[attive["data_scadenza"] <= limite] if not attive.empty else attive)

    # --- KPI ---
    tot_orizzonte = float(attive[attive["data_scadenza"] <= limite]["importo"].sum()) if not attive.empty else 0.0
    scadute = attive[attive["data_scadenza"] < oggi] if not attive.empty else attive
    al_giorno = sum(accantonamento(r["importo"], r["data_scadenza"])[0]
                    for _, r in attive.iterrows()
                    if r["data_scadenza"] >= oggi and r["data_scadenza"] <= limite) if not attive.empty else 0.0

    dom_30 = attive[
        (attive["tipo"] == "domiciliazione")
        & (attive["data_scadenza"] <= oggi + relativedelta(days=GIORNI_COPERTURA))
    ] if not attive.empty else attive
    tot_dom = float(dom_30["importo"].sum()) if not dom_30.empty else 0.0
    copre = saldo - tot_dom

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi("Totale sei mesi", eur(tot_orizzonte))
    with c2:
        kpi("Da accantonare al giorno", eur(al_giorno), C["verde"])
    with c3:
        kpi("Scadute non pagate", eur(float(scadute["importo"].sum()) if not scadute.empty else 0),
            C["rosso"] if not scadute.empty else C["muted"])
    with c4:
        kpi(f"Saldo dopo domiciliazioni {GIORNI_COPERTURA} g", eur(copre),
            C["verde"] if copre >= 0 else C["rosso"])

    if tot_dom > 0 and copre < 0:
        st.error(f"Il conto non copre le domiciliazioni dei prossimi {GIORNI_COPERTURA} giorni: "
                 f"servono {eur(tot_dom)}, sul conto ci sono {eur(saldo)}. Mancano {eur(abs(copre))}.")

    # --- Alert < 20 giorni ---
    if not attive.empty:
        alert = attive[attive["data_scadenza"] <= oggi + relativedelta(days=GIORNI_ALERT)]
        if not alert.empty:
            righe = " · ".join(
                f"{r['descrizione']} {r['data_scadenza'].strftime('%d/%m')} {eur(r['importo'])}"
                for _, r in alert.sort_values("data_scadenza").iterrows()
            )
            st.warning(f"In scadenza entro {GIORNI_ALERT} giorni ({len(alert)}): {righe}")

    # --- Elenco cronologico ---
    st.markdown('<div class="sezione">Da pagare</div>', unsafe_allow_html=True)
    da_pagare = attive[attive["tipo"] == "pagamento"] if not attive.empty else attive
    if da_pagare.empty:
        st.caption("Nessuna scadenza aperta. Aggiungine una dalla scheda Aggiungi.")
    else:
        for _, r in da_pagare.sort_values("data_scadenza").iterrows():
            riga_voce(r)

    st.markdown('<div class="sezione">Domiciliazioni · addebito automatico</div>',
                unsafe_allow_html=True)
    st.caption("Non devi pagarle tu: controlla solo che il conto sia capiente.")
    dom = attive[attive["tipo"] == "domiciliazione"] if not attive.empty else attive
    if dom.empty:
        st.caption("Nessuna domiciliazione in programma.")
    else:
        for _, r in dom.sort_values("data_scadenza").iterrows():
            riga_voce(r)


def pagina_aggiungi():
    utente = st.session_state.get("utente", "")
    modo = st.radio("Cosa vuoi inserire",
                    ["Spesa singola", "Spesa a rate", "Spesa ricorrente"],
                    horizontal=True, label_visibility="collapsed")

    # ---------- Singola ----------
    if modo == "Spesa singola":
        with st.form("f_singola", clear_on_submit=True):
            c1, c2 = st.columns([2, 1])
            desc = c1.text_input("Descrizione")
            importo = c2.number_input("Importo €", min_value=0.0, step=10.0, format="%.2f")
            c3, c4, c5 = st.columns(3)
            scad = c3.date_input("Scadenza", value=date.today())
            cat = c4.selectbox("Categoria", CATEGORIE)
            tipo = c5.selectbox("Tipo", ["Da pagare", "Domiciliazione"])
            note = st.text_input("Note", placeholder="facoltative")
            if st.form_submit_button("Aggiungi spesa"):
                if not desc or importo <= 0:
                    st.error("Servono descrizione e importo maggiore di zero.")
                else:
                    inserisci_spese([{
                        "descrizione": desc, "categoria": cat, "importo": importo,
                        "data_scadenza": scad.isoformat(),
                        "tipo": "domiciliazione" if tipo == "Domiciliazione" else "pagamento",
                        "note": note, "origine": "singola", "creata_da": utente,
                    }])
                    st.success(f"{desc} aggiunta al {scad.strftime('%d/%m/%Y')}.")

    # ---------- Rate ----------
    elif modo == "Spesa a rate":
        c1, c2, c3 = st.columns([2, 1, 1])
        desc = c1.text_input("Descrizione", key="r_desc")
        importo = c2.number_input("Importo singola rata €", min_value=0.0, step=10.0,
                                  format="%.2f", key="r_imp")
        n_rate = c3.number_input("Numero rate", min_value=1, max_value=120, value=6, step=1)
        c4, c5, c6 = st.columns(3)
        cat = c4.selectbox("Categoria", CATEGORIE, key="r_cat")
        tipo = c5.selectbox("Tipo", ["Da pagare", "Domiciliazione"], key="r_tipo")
        modalita = c6.selectbox("Scadenze", ["Automatiche", "Le inserisco io"])

        date_rate = []
        if modalita == "Automatiche":
            c7, c8 = st.columns(2)
            prima = c7.date_input("Prima scadenza", value=date.today())
            passo = c8.selectbox("Ogni", ["1 mese", "2 mesi", "3 mesi", "6 mesi", "12 mesi"])
            mesi = int(passo.split()[0])
            base_giorno = prima.day
            date_rate = [giorno_valido((prima + relativedelta(months=mesi * i)).year,
                                       (prima + relativedelta(months=mesi * i)).month,
                                       base_giorno) for i in range(int(n_rate))]
            st.caption("Scadenze generate: " +
                       ", ".join(d.strftime("%d/%m/%y") for d in date_rate))
        else:
            st.caption("Inserisci la data di ogni rata.")
            cols = st.columns(4)
            for i in range(int(n_rate)):
                d = cols[i % 4].date_input(f"Rata {i + 1}",
                                           value=date.today() + relativedelta(months=i),
                                           key=f"rata_{i}")
                date_rate.append(d)

        if st.button("Aggiungi le rate", type="primary"):
            if not desc or importo <= 0:
                st.error("Servono descrizione e importo maggiore di zero.")
            else:
                gruppo = str(uuid.uuid4())
                righe = [{
                    "descrizione": desc, "categoria": cat, "importo": importo,
                    "data_scadenza": d.isoformat(),
                    "tipo": "domiciliazione" if tipo == "Domiciliazione" else "pagamento",
                    "gruppo_id": gruppo, "rata_num": i + 1, "rata_tot": int(n_rate),
                    "origine": "rata", "creata_da": utente,
                } for i, d in enumerate(sorted(date_rate))]
                inserisci_spese(righe)
                st.success(f"{int(n_rate)} rate aggiunte per un totale di "
                           f"{eur(importo * int(n_rate))}.")

    # ---------- Ricorrente ----------
    else:
        st.caption("Spesa che si ripete senza una fine: affitto, abbonamenti, bollette. "
                   "L'app la rigenera da sola sui sei mesi successivi.")
        with st.form("f_ric", clear_on_submit=True):
            c1, c2, c3 = st.columns([2, 1, 1])
            desc = c1.text_input("Descrizione")
            importo = c2.number_input("Importo €", min_value=0.0, step=10.0, format="%.2f")
            giorno = c3.number_input("Giorno del mese", min_value=1, max_value=31, value=1)
            c4, c5, c6 = st.columns(3)
            cat = c4.selectbox("Categoria", CATEGORIE)
            ogni = c5.selectbox("Ogni", ["1 mese", "2 mesi", "3 mesi", "6 mesi", "12 mesi"])
            tipo = c6.selectbox("Tipo", ["Da pagare", "Domiciliazione"])
            inizio = st.date_input("Attiva dal", value=date.today())
            if st.form_submit_button("Aggiungi ricorrente"):
                if not desc or importo <= 0:
                    st.error("Servono descrizione e importo maggiore di zero.")
                else:
                    db().table("casa_ricorrenti").insert({
                        "descrizione": desc, "categoria": cat, "importo": importo,
                        "giorno_mese": int(giorno), "ogni_mesi": int(ogni.split()[0]),
                        "tipo": "domiciliazione" if tipo == "Domiciliazione" else "pagamento",
                        "data_inizio": inizio.isoformat(), "attiva": True,
                    }).execute()
                    n = genera_da_ricorrenti()
                    st.success(f"{desc} attivata. Create {n} scadenze.")


def pagina_riepilogo(spese: pd.DataFrame):
    if spese.empty:
        st.caption("Ancora nessun dato da riepilogare.")
        return

    pagate = spese[spese["pagata"]].copy()
    attive = spese[~spese["pagata"]].copy()

    c1, c2, c3 = st.columns(3)
    with c1:
        kpi("Pagato quest'anno",
            eur(pagate[pd.to_datetime(pagate["data_pagamento"]).dt.year == date.today().year]["importo"].sum()
                if not pagate.empty else 0))
    with c2:
        kpi("Voci in archivio", str(len(pagate)))
    with c3:
        kpi("Voci aperte", str(len(attive)))

    # Storico mensile del pagato
    if not pagate.empty:
        st.markdown('<div class="sezione">Storico pagamenti</div>', unsafe_allow_html=True)
        p = pagate.dropna(subset=["data_pagamento"]).copy()
        if not p.empty:
            p["mese"] = pd.to_datetime(p["data_pagamento"]).dt.to_period("M").astype(str)
            serie = p.groupby("mese")["importo"].sum().tail(18)
            fig = go.Figure(go.Bar(x=list(serie.index), y=list(serie.values),
                                   marker_color=C["verde"],
                                   hovertemplate="%{y:.2f} €<extra></extra>"))
            fig.update_layout(height=260, margin=dict(l=0, r=0, t=10, b=0),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              font=dict(color=C["text"], size=12),
                              xaxis=dict(showgrid=False, linecolor=C["line"]),
                              yaxis=dict(gridcolor=C["line"], tickformat=",.0f"),
                              bargap=0.5)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        st.markdown('<div class="sezione">Spesa per categoria</div>', unsafe_allow_html=True)
        per_cat = pagate.groupby("categoria")["importo"].sum().sort_values(ascending=True)
        fig2 = go.Figure(go.Bar(x=list(per_cat.values), y=list(per_cat.index),
                                orientation="h", marker_color=C["domic"],
                                hovertemplate="%{x:.2f} €<extra></extra>"))
        fig2.update_layout(height=max(220, 34 * len(per_cat)),
                           margin=dict(l=0, r=0, t=10, b=0),
                           paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           font=dict(color=C["text"], size=12),
                           xaxis=dict(gridcolor=C["line"], tickformat=",.0f"),
                           yaxis=dict(showgrid=False))
        st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

    # Archivio
    st.markdown('<div class="sezione">Archivio</div>', unsafe_allow_html=True)
    if pagate.empty:
        st.caption("L'archivio si riempie quando segni una voce come pagata.")
    else:
        anni = sorted({d.year for d in pagate["data_scadenza"]}, reverse=True)
        c1, c2 = st.columns([1, 2])
        anno = c1.selectbox("Anno", ["Tutti"] + [str(a) for a in anni])
        cerca = c2.text_input("Cerca", placeholder="descrizione o categoria")

        vista = pagate.copy()
        if anno != "Tutti":
            vista = vista[[d.year == int(anno) for d in vista["data_scadenza"]]]
        if cerca:
            m = vista["descrizione"].str.contains(cerca, case=False, na=False) | \
                vista["categoria"].fillna("").str.contains(cerca, case=False, na=False)
            vista = vista[m]

        st.caption(f"{len(vista)} voci · totale {eur(vista['importo'].sum())}")
        for _, r in vista.sort_values("data_scadenza", ascending=False).iterrows():
            riga_voce(r, archivio=True)

    # Export
    st.markdown('<div class="sezione">Esporta</div>', unsafe_allow_html=True)
    export = spese.copy()
    export["data_pagamento"] = pd.to_datetime(export["data_pagamento"], errors="coerce").dt.date
    csv = export[COLONNE_SPESE[1:]].to_csv(index=False, sep=";", decimal=",")
    st.download_button("Scarica tutto in CSV", csv.encode("utf-8-sig"),
                       file_name=f"spese_{date.today().isoformat()}.csv", mime="text/csv")


def pagina_impostazioni(saldo: float):
    st.markdown('<div class="sezione">Saldo del conto</div>', unsafe_allow_html=True)
    st.caption("Serve a capire se le domiciliazioni dei prossimi 30 giorni sono coperte. "
               "Aggiornalo quando controlli il conto.")
    c1, c2 = st.columns([1, 3])
    nuovo = c1.number_input("Saldo €", min_value=0.0, value=float(saldo), step=50.0,
                            format="%.2f", label_visibility="collapsed")
    if c2.button("Salva saldo"):
        scrivi_saldo(nuovo)
        st.success("Saldo aggiornato.")
        st.rerun()

    st.markdown('<div class="sezione">Spese ricorrenti</div>', unsafe_allow_html=True)
    ric = carica_ricorrenti()
    if ric.empty:
        st.caption("Nessuna ricorrente attiva.")
    else:
        for _, r in ric.iterrows():
            c1, c2, c3 = st.columns([5, 1.2, 1.2])
            stato = "attiva" if r["attiva"] else "sospesa"
            colore = C["verde"] if r["attiva"] else C["muted"]
            c1.markdown(
                f"""<div class="voce" style="border-left-color:{colore}">
                  <div class="riga1"><span class="desc">{r['descrizione']}</span>
                  <span class="imp">{eur(r['importo'])}</span></div>
                  <div class="riga2">giorno {int(r['giorno_mese'])} · ogni {int(r['ogni_mesi'])} mese/i
                  · {r['categoria']} · {stato}</div></div>""",
                unsafe_allow_html=True)
            if c2.button("Sospendi" if r["attiva"] else "Riattiva", key=f"tog_{r['id']}",
                         use_container_width=True):
                db().table("casa_ricorrenti").update({"attiva": not r["attiva"]}).eq("id", r["id"]).execute()
                st.rerun()
            if c3.button("Elimina", key=f"delric_{r['id']}", use_container_width=True):
                db().table("casa_spese").delete().eq("gruppo_id", r["id"]).eq("pagata", False)\
                    .gte("data_scadenza", date.today().isoformat()).execute()
                db().table("casa_ricorrenti").delete().eq("id", r["id"]).execute()
                st.rerun()

    if st.button("Rigenera scadenze ricorrenti"):
        n = genera_da_ricorrenti()
        st.success(f"Create {n} nuove scadenze." if n else "Tutto già aggiornato.")

    st.markdown('<div class="sezione">Sessione</div>', unsafe_allow_html=True)
    if st.button("Esci"):
        st.session_state.clear()
        st.rerun()


# ----------------------------------------------------------------------------
# Avvio
# ----------------------------------------------------------------------------

def main():
    if not login():
        return

    if "ricorrenti_generate" not in st.session_state:
        try:
            genera_da_ricorrenti()
        except Exception as e:
            st.warning(f"Ricorrenti non generate: {e}")
        st.session_state.ricorrenti_generate = True

    spese = carica_spese()
    saldo = leggi_saldo()

    st.markdown('<div class="titolo">Scadenze & Spese</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="sottotitolo">Ciao {st.session_state.utente} · '
        f'{date.today().strftime("%d/%m/%Y")} · saldo conto {eur(saldo)}</div>',
        unsafe_allow_html=True)

    t1, t2, t3, t4 = st.tabs(["Scadenze", "Aggiungi", "Riepilogo e archivio", "Impostazioni"])
    with t1:
        pagina_scadenze(spese, saldo)
    with t2:
        pagina_aggiungi()
    with t3:
        pagina_riepilogo(spese)
    with t4:
        pagina_impostazioni(saldo)


if __name__ == "__main__":
    main()
