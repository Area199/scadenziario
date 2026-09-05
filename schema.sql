-- Esegui questo file nel SQL Editor di Supabase (una volta sola).
-- Le tabelle usano il prefisso casa_ per convivere senza collisioni
-- con quelle di altre app nello stesso progetto.

create extension if not exists "pgcrypto";

-- Scadenze singole, rate e occorrenze generate dalle ricorrenti
create table if not exists casa_spese (
  id             uuid primary key default gen_random_uuid(),
  descrizione    text not null,
  categoria      text,
  importo        numeric(12,2) not null,
  data_scadenza  date not null,
  tipo           text not null default 'pagamento',   -- 'pagamento' | 'domiciliazione'
  gruppo_id      uuid,                                 -- rate o ricorrente di origine
  rata_num       int,
  rata_tot       int,
  note           text,
  pagata         boolean not null default false,
  data_pagamento date,
  origine        text default 'singola',               -- 'singola' | 'rata' | 'ricorrente'
  creata_da      text,
  created_at     timestamptz default now()
);

create index if not exists casa_spese_scadenza_idx on casa_spese (data_scadenza);
create index if not exists casa_spese_pagata_idx   on casa_spese (pagata);
create index if not exists casa_spese_gruppo_idx   on casa_spese (gruppo_id);

-- Spese che si ripetono senza una fine
create table if not exists casa_ricorrenti (
  id           uuid primary key default gen_random_uuid(),
  descrizione  text not null,
  categoria    text,
  importo      numeric(12,2) not null,
  giorno_mese  int not null default 1,
  ogni_mesi    int not null default 1,
  tipo         text not null default 'pagamento',
  data_inizio  date not null default current_date,
  attiva       boolean not null default true,
  created_at   timestamptz default now()
);

-- Saldo del conto (riga unica)
create table if not exists casa_conto (
  id            int primary key default 1,
  saldo         numeric(12,2) not null default 0,
  aggiornato_at timestamptz default now(),
  constraint casa_conto_riga_unica check (id = 1)
);

insert into casa_conto (id, saldo) values (1, 0) on conflict (id) do nothing;

-- L'app gira lato server e la chiave sta nei secrets di Streamlit,
-- quindi queste tabelle non sono raggiungibili dal browser.
alter table casa_spese      disable row level security;
alter table casa_ricorrenti disable row level security;
alter table casa_conto      disable row level security;
