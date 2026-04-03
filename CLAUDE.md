# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Jezik / Language

Projekt je namenjen slovensko govorečim uporabnikom. Vsa komunikacija s Claude poteka v **slovenščini**. Komentarji v kodi so v angleščini (HA standard), UI prevodi pa v slovenščini in angleščini.

## Projekt

**spar_si** — Home Assistant custom component integracija za [online.spar.si](https://online.spar.si/) (SPAR Online spletna trgovina z živili v Sloveniji).

### Vizija
Voice assistant v HA (slovenščina) -> uporabnik doda izdelke na nakupovalni seznam -> AI poišče izdelke v SPAR Online -> doda v košarico -> uporabnik potrdi in naroči dostavo na dom.

### Ključne funkcionalnosti
- **Todo entiteta "Nakupovalni seznam"** — lokalni seznam želenih izdelkov (ročno ali preko voice)
- **Todo entiteta "SPAR Košarica"** — sinhroniziran s SPAR Online cart
- **Iskanje izdelkov** — GraphQL API za iskanje po imenu/SKU
- **Upravljanje košarice** — dodaj/odstrani/posodobi izdelke v SPAR Online košarici
- **Sinhronizacija** — med lokalnim seznamom in SPAR Online košarico

## Arhitektura

### Backend API (online.spar.si)
- Platforma: **Instaleap "Deadpool"** (white-label e-commerce)
- API: **GraphQL** (Apollo Server)
  - v2: `https://deadpool.unified-jennet.instaleap.io/api/v2` (katalog, auth)
  - v3: `https://deadpool.unified-jennet.instaleap.io/api/v3` (cart, e-commerce)
- Avtentikacija: Firebase Auth (projekt `spar-slovenia`) -> Instaleap JWT
- Ključni headerji: `dpl-api-key`, `token` (JWT), `client-name`

### HA Integracija struktura
```
custom_components/spar_si/
  __init__.py          # async_setup_entry, async_unload_entry
  manifest.json        # domain: spar_si, iot_class: cloud_polling
  config_flow.py       # email/password credentials setup + reauth
  const.py             # konstante (DOMAIN, API URLs, keys)
  coordinator.py       # DataUpdateCoordinator za cart polling
  api.py               # async API klient (aiohttp) za SPAR GraphQL
  todo.py              # TodoListEntity za seznam + košarico
  services.yaml        # search_products, add_to_cart, sync_list
  translations/
    en.json
    sl.json
```

## Ukazi za razvoj

```bash
# Lint
ruff check custom_components/spar_si/
ruff format --check custom_components/spar_si/

# Type check
mypy custom_components/spar_si/

# Testi
pytest tests/ -v
pytest tests/test_api.py -v -k "test_search"   # posamezen test

# Preveri manifest
python -c "import json; json.load(open('custom_components/spar_si/manifest.json'))"
```

## Pravila razvoja

- Sledi HA coding standardom: async/await, aiohttp, DataUpdateCoordinator pattern
- Custom components NE smejo uporabljati `strings.json` — uporabi `translations/` z polnimi prevodi
- Vse API klice ovij v `async_timeout.timeout()`
- `entry.runtime_data` namesto `hass.data[DOMAIN]` (moderni pattern)
- `_attr_has_entity_name = True` za vse entitete
- Pri auth napakah sproži `ConfigEntryAuthFailed` za avtomatski reauth flow
- GitHub account: **andrejs2**

## Session logi

Napredek in session logi se shranjujejo v `docs/sessions/`. Vsak session ima svoj log.
