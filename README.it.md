<p align="center">
  <a href="https://www.ilmeteo.it/" target="_blank"><img src="https://raw.githubusercontent.com/giorgioparri/ha-ilmeteo/HEAD/images/logo.png" alt="iLMeteo.it" width="120"></a>
</p>

<p align="right"><a href="https://github.com/giorgioparri/ha-ilmeteo/blob/HEAD/README.md">🇬🇧 Read in English</a></p>

# iLMeteo.it — Integrazione personalizzata per Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/default)
[![GitHub Release](https://img.shields.io/github/release/giorgioparri/ha-ilmeteo.svg)](https://github.com/giorgioparri/ha-ilmeteo/releases)
[![Validate](https://github.com/giorgioparri/ha-ilmeteo/actions/workflows/validate.yml/badge.svg)](https://github.com/giorgioparri/ha-ilmeteo/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/giorgioparri/ha-ilmeteo)](https://github.com/giorgioparri/ha-ilmeteo/blob/HEAD/LICENSE)

[![Apri la tua istanza Home Assistant e aggiungi questa integrazione.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=giorgioparri&repository=ha-ilmeteo&category=integration)

Un'integrazione per [Home Assistant](https://www.home-assistant.io/) che espone i dati meteo di **[iLMeteo.it](https://www.ilmeteo.it/)** come entità `weather` native, con previsioni **giornaliere** e **orarie** — esattamente come le integrazioni OpenWeatherMap o Met.no.

> **Come funziona:** dalla versione 2.0 l'integrazione usa le API ufficiali di iLMeteo.it. Ogni utente ha bisogno di una chiave API personale, da generare nella propria area riservata di iLMeteo.it e da inserire una sola volta in Home Assistant.

---

## ⚠️ Note importanti

- **Serve una chiave API.** Generala nella tua area riservata di iLMeteo.it, poi incollala quando aggiungi l'integrazione. La chiave resta sulla tua istanza di Home Assistant e non fa mai parte di questo repository.
- **Limite giornaliero:** ogni chiave ha 1000 richieste al giorno, azzerate a mezzanotte (ora italiana) e condivise da tutte le località che la usano. Con un aggiornamento ogni 30 minuti, una località usa circa 100 richieste al giorno. Se il limite si esaurisce, le ultime previsioni restano visibili e continuano ad avanzare ora per ora, compare una notifica e gli aggiornamenti riprendono dopo la mezzanotte.
- L'integrazione mostra l'attribuzione "Dati meteo forniti da iLMeteo.it (www.ilmeteo.it)" sull'entità.
- La pagina del dispositivo (Impostazioni → Dispositivi e servizi → dispositivo) include un link "Visita" alla pagina della località su iLMeteo.it.
- Progetto indipendente, pubblicato con il permesso di iLMeteo Srl. Il supporto si trova qui su GitHub, non presso iLMeteo.
- Il logo e il marchio "iLMeteo" sono di proprietà di iLMeteo Srl e vengono utilizzati esclusivamente per identificare la fonte dei dati.

---

## Funzionalità

- Entità `weather` nativa con condizioni attuali, temperatura percepita, punto di rugiada, umidità, pressione, visibilità, indice UV, vento e raffiche
- **Previsioni giornaliere** per 8 giorni, con temperatura minima e massima, quantità e probabilità di precipitazioni, vento e pressione
- **Previsioni orarie** fino alla fine di dopodomani, uno slot per ogni ora
- Condizioni giorno/notte dai dati di iLMeteo.it (es. `sunny` → `clear-night`), e `pouring` per la pioggia forte
- **Ricerca della località** per nome, per distanza da casa o per regione e provincia — frazioni e quartieri compresi
- Supporto **multi-località**: ogni località è un'istanza separata, tutte con la stessa chiave
- **Notifiche di allerta meteo**, attive per impostazione predefinita: soglie euristiche sui dati iLMeteo, più una fonte ufficiale della Protezione Civile opzionale
- Configurazione da UI — nessun YAML

## Screenshot

![iLMeteo.it weather card](https://raw.githubusercontent.com/giorgioparri/ha-ilmeteo/v2.0.0-beta.3/images/card-demo.png)

---

## Installazione

### Tramite HACS (consigliato)

1. Apri HACS e cerca **iLMeteo.it**
2. Installa, poi riavvia Home Assistant

L'integrazione è nel catalogo predefinito di HACS: non serve aggiungere un repository personalizzato.

### Manuale

1. Scarica l'ultima [release](https://github.com/giorgioparri/ha-ilmeteo/releases/latest)
2. Copia `custom_components/ilmeteo` in `/config/custom_components/`
3. Riavvia Home Assistant

### Aggiornamento dalla 1.x

Dopo l'aggiornamento e il riavvio, Home Assistant chiede di autenticare di nuovo iLMeteo.it in **Impostazioni → Dispositivi e servizi**. Inserisci la chiave API una volta sola: vale per tutte le località configurate. Località, entità, opzioni e cronologia restano. Una notifica, mostrata una sola volta, elenca poi i nuovi sensori opzionali, che puoi attivare da **Configura**.

---

## Configurazione

1. **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → iLMeteo.it**
2. Inserisci la **chiave API** (richiesta solo per la prima località; per le successive viene proposta la stessa)
3. Scegli la località: **vicino alla posizione di casa** (entro 15 km), **cerca per nome** (es. "Roma Monte Sacro") oppure **regione → provincia → località**
4. Se vuoi, imposta un nome visualizzato, i sensori dedicati e le notifiche di allerta

Alcune frazioni e alcuni quartieri non hanno una previsione propria e usano quella di una località vicina: l'elenco lo indica accanto al nome. Per aggiungere altre località, ripeti la procedura.

### Nome entità e nome visualizzato

Ogni istanza riceve un identificatore tecnico generico e permanente — `weather.ilmeteo_site_1`, `weather.ilmeteo_site_2`, ecc. — assegnato una volta alla creazione e mai riutilizzato, anche se l'istanza viene rimossa.

Il *nome visualizzato* (mostrato nell'UI, es. "iLMeteo.it Roma") è separato e completamente personalizzabile: viene chiesto durante la configurazione (con il nome della località come default, modificabile) e può essere cambiato in qualsiasi momento tramite il menu **Configura** (Opzioni) dell'integrazione. La modifica non influisce mai sull'ID tecnico dell'entità.

### Cambiare la località monitorata

Apri il menu a tre punti dell'integrazione → **Riconfigura** per puntare un'istanza esistente a una località diversa (stesse scelte della configurazione iniziale). Questo cambia *da dove arrivano i dati*; il nome visualizzato viene reimpostato al nome della nuova località (personalizzabile di nuovo tramite Opzioni), mentre gli ID entità, il dispositivo e i sensori abilitati rimangono invariati.

### Sensori dedicati opzionali

Oltre all'entità `weather` principale, puoi abilitare entità `sensor` dedicate — durante la configurazione iniziale o in qualsiasi momento tramite **Configura** (Opzioni):

- *Ora corrente:* temperatura, temperatura percepita, punto di rugiada, umidità, pressione, visibilità, indice UV, irraggiamento solare stimato, velocità del vento, raffica, direzione del vento, precipitazione nell'ora, quota dello zero termico, quota neve
- *Oggi:* temperatura minima e massima, probabilità di precipitazioni, precipitazione totale, affidabilità della previsione

Questi sensori esistono specificamente per supportare le statistiche a lungo termine e i grafici storici di Home Assistant, che gli attributi dell'entità meteo non possono fornire (gli attributi non hanno `state_class`). Sono **disattivati per impostazione predefinita** — nulla cambia per le installazioni esistenti finché non si opta esplicitamente. Deselezionare un sensore già attivo lo elimina, inclusa la sua cronologia.

### Notifiche di allerta meteo

**Attive per impostazione predefinita** (toggle nella configurazione iniziale e in qualsiasi momento tramite **Configura** → Opzioni). Quando abilitate, ogni località viene monitorata per allerte meteo da fino a due fonti indipendenti, valutate in parallelo:

- **Euristica** (sempre attiva quando le allerte sono abilitate): allerte basate su soglie — caldo/freddo estremo, vento forte, temporali, grandine, alta probabilità di pioggia — derivate dagli stessi dati di previsione già scaricati per l'entità meteo, senza richieste aggiuntive. Valutate separatamente per oggi e domani. **Non è un'allerta ufficiale**: le API di iLMeteo.it non forniscono dati di allerta, quindi queste soglie sono definite dall'integrazione stessa (modificabili in `alerts.py`).
- **Protezione Civile** (opzionale): legge i dati di allerta in tempo reale dall'integrazione [DPC Alert](https://github.com/caiosweet/Home-Assistant-custom-components-DPC-Alert) di caiosweet, se installata e configurata per questa località. Nessuna richiesta HTTP aggiuntiva — questa integrazione legge soltanto lo stato dell'entità che DPC Alert mantiene aggiornato.

**Quali entità DPC usare:** DPC Alert espone diversi sensori; solo due sono utili qui. Usa **`sensor.dpc_alert`** (campo `dpc_alert_entity_id`) per il bollettino ufficiale di criticità idrogeologica e idraulica (oggi e domani, tutti i tipi di rischio con livello di severità), e **`sensor.dpc_vigilance`** (campo `dpc_vigilance_entity_id`) per il bollettino di vigilanza meteorologica che copre oggi, domani e dopodomani (vento, neve, temporali e altri fenomeni con distanza e direzione dalla tua posizione). I due sensori sono complementari e possono essere entrambi attivi contemporaneamente. I sei binary sensor (`dpc_idraulico_*`, `dpc_idrogeologico_*`, `dpc_temporali_*`) sono viste semplificate on/off degli stessi dati e non servono qui.

Entrambe le fonti possono essere attive contemporaneamente — le allerte di ciascuna portano un attributo `source` per distinguerle nelle automazioni.

Ogni notifica di allerta include un link alla pagina iLMeteo.it della località. Canali di consegna:

- Una `persistent_notification` viene sempre creata (e rimossa quando l'allerta rientra) — resa con il logo iLMeteo e un link cliccabile nel frontend HA.
- Opzionalmente, push verso uno o più **dispositivi mobili con il companion app** tramite l'opzione `notify_targets` (vuota per impostazione predefinita). Il link iLMeteo è surfacciato come bottone d'azione tappable ("Apri iLMeteo.it") poiché il push nativo non renderizza il Markdown. Sono supportati solo i target `notify.mobile_app_*` — le nuove entità notify (HA 2026.5+) non supportano ancora il payload dati del companion app.
- Un evento `ilmeteo_weather_alert` viene sparato ad ogni nuova allerta, cambio di severità o rientro (`alert_id`, `severity`, `kind`, `title`, `message`, `source`, `link`, `cleared`), per costruire automazioni personalizzate.

Le allerte vengono deduplicate per `alert_id` + severità e persistite attraverso i riavvii, quindi ricevi una notifica solo quando un'allerta compare per la prima volta o peggiora, non ad ogni refresh di 30 minuti.

## Dati esposti

**Condizioni attuali** *(l'ora di previsione che contiene il momento attuale)*: `condition`, `temperature`, `apparent_temperature`, `dew_point`, `humidity`, `pressure`, `visibility`, `uv_index`, `wind_speed`, `wind_gust_speed`, `wind_bearing`

**Previsione giornaliera** *(8 giorni)*: condizione, temperatura max/min, quantità e probabilità di precipitazioni, pressione, velocità, raffica e direzione del vento

**Previsione oraria** *(uno slot per ogni ora)*: condizione, temperatura, temperatura percepita, punto di rugiada, umidità, precipitazioni, pressione, velocità, raffica e direzione del vento, indice UV

---

## Sviluppo e test

I moduli che parlano con le API e decidono cosa fare (`client.py`, `quota.py`, `update.py`, `alerts.py`, `const.py`) non dipendono da Home Assistant, quindi i loro test girano come semplici script. Serve solo `aiohttp`:

```bash
pip install aiohttp
python tests/test_api.py
python tests/test_quota.py
python tests/test_update.py
python tests/test_alerts.py
python tests/test_conditions.py
```

I test del client API girano contro un gateway finto locale che serve le fixture JSON in `tests/fixtures/`: non servono né una chiave API né l'accesso alla rete.

I moduli che importano Home Assistant (coordinator, config flow, entità, `alert_manager.py`) non sono coperti da questi script; per testarli serve `pytest-homeassistant-custom-component`.

---

## Changelog

Vedi [CHANGELOG.md](https://github.com/giorgioparri/ha-ilmeteo/blob/HEAD/CHANGELOG.md) per la cronologia completa delle versioni.

---

## Licenza

Apache-2.0 — vedi [LICENSE](https://github.com/giorgioparri/ha-ilmeteo/blob/HEAD/LICENSE)

## Disclaimer

Questa è un'integrazione indipendente, pubblicata con il permesso di iLMeteo Srl, che non ne fornisce il supporto. I dati meteo vengono recuperati dalle API di iLMeteo.it con la tua chiave personale. Usare a proprio rischio e in conformità con i [termini di utilizzo](https://www.ilmeteo.it/portale/termini_e_condizioni) di iLMeteo.

## Ringraziamenti

Built with the assistance of [Claude](https://claude.ai) by Anthropic.
