# Scadenze & Spese

App Streamlit per gestire in due le scadenze di casa: pagamenti, rate, domiciliazioni e spese ricorrenti, con accantonamento giornaliero e archivio storico.

## Cosa fa

- **Scadenze** — riepilogo a barre dei prossimi 6 mesi con totale per mese, alert per tutto ciò che scade entro 20 giorni, elenco cronologico. Sotto ogni voce quanto serve accantonare al giorno, a settimana e al mese.
- **Domiciliazioni** — elencate a parte e in blu, con controllo saldo: se il conto non copre gli addebiti dei prossimi 30 giorni compare un avviso rosso con la cifra mancante.
- **Aggiungi** — spesa singola, spesa a rate (scadenze generate in automatico ogni N mesi oppure inserite una per una) e spesa ricorrente senza fine, che l'app rigenera da sola sui 6 mesi successivi.
- **Riepilogo e archivio** — pagato per mese, spesa per categoria, archivio ricercabile per anno e testo, export CSV.
- **Impostazioni** — saldo del conto, gestione ricorrenti, logout.

Semaforo scadenze: rosso se scaduta o entro 7 giorni, ambra entro 20, blu per le domiciliazioni lontane, verde in archivio.

## Setup

1. **Supabase** — apri il SQL Editor del progetto e lancia `schema.sql`. Le tabelle si chiamano `casa_spese`, `casa_ricorrenti`, `casa_conto`: il prefisso permette di condividere il progetto con un'altra app senza collisioni.
2. **Secrets** — copia `.streamlit/secrets.toml.example` in `.streamlit/secrets.toml` e compila:

```toml
SUPABASE_URL = "https://xxxx.supabase.co"
SUPABASE_KEY = "anon key"

[auth]
Marco = "password-tua"
Sara  = "password-di-tua-moglie"
```

Ogni password identifica una persona: il nome finisce nel saluto e nel campo `creata_da`.

3. **In locale**

```bash
pip install -r requirements.txt
streamlit run app.py
```

4. **Streamlit Community Cloud** — pusha il repo, crea la app puntando ad `app.py`, poi incolla il contenuto di `secrets.toml` in *Settings → Secrets*. Niente file di dati nel repo: tutto sta su Supabase, quindi i riavvii non cancellano nulla.

## Note

- Si usa il client REST di Supabase (`supabase-py`), non la connessione Postgres diretta: quest'ultima risponde solo su IPv6 e da Streamlit Cloud non è raggiungibile.
- RLS è disattivata perché le query partono dal server Streamlit e la chiave sta nei secrets, mai nel browser. Non pubblicare `secrets.toml` su GitHub (è già in `.gitignore`).
- Il progetto Supabase può essere condiviso con altre app: bastano la stessa `SUPABASE_URL` e la stessa anon key nei secrets di questa app.
- Le ricorrenti vengono generate al primo caricamento di ogni sessione, e comunque dal pulsante *Rigenera scadenze ricorrenti*.
- Eliminando una ricorrente spariscono anche le sue scadenze future non pagate; lo storico resta.
