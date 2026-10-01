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

Un'integrazione per [Home Assistant](https://www.home-assistant.io/) che espone i dati meteo di **[iLMeteo.it](https://www.ilmeteo.it/)** come entità `weather` native, con previsioni **giornaliere** e **orarie** (triorarie) — esattamente come le integrazioni OpenWeatherMap o Met.no.

> **Come funziona:** Le API REST ufficiali di iLMeteo sono riservate ai clienti business. Questa integrazione utilizza invece tre dei **box widget pubblici e gratuiti** che iLMeteo mette a disposizione per l'incorporamento su siti di terze parti (vedi la [pagina business portali](https://www.ilmeteo.it/business/portali)): un box con le condizioni in tempo reale, un box con il riepilogo giornaliero ufficiale per min/max e probabilità di pioggia, e un box triorario per le previsioni orarie dettagliate. Tutti parsati lato server. Nessun token richiesto.

---

## ⚠️ Note importanti

- Questa integrazione **fa scraping** di pagine web pubbliche. Non esiste una garanzia contrattuale di stabilità: se iLMeteo cambia il markup di un box, il parser potrebbe richiedere un aggiornamento. I tre box vengono scaricati in modo indipendente, quindi una variazione di layout su uno non blocca gli altri — e un vero errore di parsing genera un avviso visibile in **Impostazioni → Sistema → Riparazioni** invece di fallire silenziosamente.
- Nel rispetto dei [termini di utilizzo](https://www.ilmeteo.it/portale/termini_e_condizioni) di iLMeteo, l'integrazione mostra l'attribuzione "Dati meteo forniti da iLMeteo.it (www.ilmeteo.it)" sull'entità e interroga il servizio a bassa frequenza (ogni 30 minuti).
- La pagina del dispositivo (Impostazioni → Dispositivi e servizi → dispositivo) include un link "Visita" alla pagina del comune configurato su iLMeteo.it.
- Progetto non ufficiale, non affiliato con iLMeteo Srl.
- Il logo e il marchio "iLMeteo" sono di proprietà di iLMeteo Srl e vengono utilizzati esclusivamente per identificare la fonte dei dati.

---

## Funzionalità

- Entità `weather` nativa con **condizioni attuali in tempo reale** (non uno slot di previsione approssimato)
- **Previsioni giornaliere** fino a 6 giorni con min/max ufficiali di iLMeteo e **probabilità di precipitazioni** — non derivate da campioni orari sparsi
- **Previsioni orarie** (triorarie): 5 slot per giorno con temperatura, temperatura percepita, umidità, vento, precipitazioni
- Gestione automatica delle condizioni giorno/notte (es. `sunny` → `clear-night`)
- Supporto **multi-localita**: ogni città è un'istanza separata
- **Notifiche di allerta meteo**, attive per impostazione predefinita: soglie euristiche sui dati iLMeteo, più una fonte ufficiale della Protezione Civile opzionale
- Configurazione da UI — nessun YAML, nessun token

## Screenshot

![iLMeteo.it weather card](https://raw.githubusercontent.com/giorgioparri/ha-ilmeteo/main/images/card-demo.png)

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

---

## Configurazione

1. **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → iLMeteo.it**
2. Seleziona **regione**, poi **provincia**, poi **comune** dai menu a tendina
3. Fatto: l'entità viene creata e validata automaticamente

L'elenco completo dei comuni italiani (8.218 comuni, 110 province, 20 regioni) è incluso nell'integrazione, senza bisogno di cercare codici manualmente. Per aggiungere altre località, ripeti la procedura.

> Il dataset è generato dai codici ufficiali di iLMeteo tramite `scripts/build_locations.py` e salvato compresso (~67 KB) in `custom_components/ilmeteo/data/locations.json.gz`.

### Nome entità e nome visualizzato

Ogni istanza riceve un identificatore tecnico generico e permanente — `weather.ilmeteo_site_1`, `weather.ilmeteo_site_2`, ecc. — assegnato una volta alla creazione e mai riutilizzato, anche se l'istanza viene rimossa.

Il *nome visualizzato* (mostrato nell'UI, es. "iLMeteo.it Roma") è separato e completamente personalizzabile: viene chiesto durante la configurazione (con il nome del comune come default, modificabile) e può essere cambiato in qualsiasi momento tramite il menu **Configura** (Opzioni) dell'integrazione. La modifica non influisce mai sull'ID tecnico dell'entità.

### Cambiare la località monitorata

Apri il menu a tre punti dell'integrazione → **Riconfigura** per puntare un'istanza esistente a un comune diverso (stessa procedura regione/provincia/comune della configurazione iniziale). Questo cambia *da dove arrivano i dati*; il nome visualizzato viene reimpostato al nome del nuovo comune (personalizzabile di nuovo tramite Opzioni), mentre gli ID entità, il dispositivo e i sensori abilitati rimangono invariati.

### Sensori dedicati opzionali

Oltre all'entità `weather` principale, puoi abilitare entità `sensor` dedicate — durante la configurazione iniziale o in qualsiasi momento tramite **Configura** (Opzioni):

- Temperatura, umidità, velocità del vento, direzione del vento *(letture attuali)*
- Temperatura minima e massima giornaliera, probabilità di precipitazioni *(solo oggi — mai derivate dalla previsione multi-giorno)*

Questi sensori esistono specificamente per supportare le statistiche a lungo termine e i grafici storici di Home Assistant, che gli attributi dell'entità meteo non possono fornire (gli attributi non hanno `state_class`). Sono **disattivati per impostazione predefinita** — nulla cambia per le installazioni esistenti finché non si opta esplicitamente. Deselezionare un sensore già attivo lo elimina, inclusa la sua cronologia.

### Notifiche di allerta meteo

**Attive per impostazione predefinita** (toggle nella configurazione iniziale e in qualsiasi momento tramite **Configura** → Opzioni). Quando abilitate, ogni località viene monitorata per allerte meteo da fino a due fonti indipendenti, valutate in parallelo:

- **Euristica** (sempre attiva quando le allerte sono abilitate): allerte basate su soglie — caldo/freddo estremo, vento forte, temporali, grandine, alta probabilità di pioggia — derivate dagli stessi dati real1/day1/tri1 già scaricati per l'entità meteo. Valutate separatamente per oggi e domani. **Non è un'allerta ufficiale**: iLMeteo.it non pubblica dati di allerta strutturati nei suoi box widget pubblici, solo articoli editoriali, quindi queste soglie sono definite dall'integrazione stessa (modificabili in `alerts.py`).
- **Protezione Civile** (opzionale): legge i dati di allerta in tempo reale dall'integrazione [DPC Alert](https://github.com/caiosweet/Home-Assistant-custom-components-DPC-Alert) di caiosweet, se installata e configurata per questa località. Nessuna richiesta HTTP aggiuntiva — questa integrazione legge soltanto lo stato dell'entità che DPC Alert mantiene aggiornato.

**Quali entità DPC usare:** DPC Alert espone diversi sensori; solo due sono utili qui. Usa **`sensor.dpc_alert`** (campo `dpc_alert_entity_id`) per il bollettino ufficiale di criticità idrogeologica e idraulica (oggi e domani, tutti i tipi di rischio con livello di severità), e **`sensor.dpc_vigilance`** (campo `dpc_vigilance_entity_id`) per il bollettino di vigilanza meteorologica che copre oggi, domani e dopodomani (vento, neve, temporali e altri fenomeni con distanza e direzione dalla tua posizione). I due sensori sono complementari e possono essere entrambi attivi contemporaneamente. I sei binary sensor (`dpc_idraulico_*`, `dpc_idrogeologico_*`, `dpc_temporali_*`) sono viste semplificate on/off degli stessi dati e non servono qui.

Entrambe le fonti possono essere attive contemporaneamente — le allerte di ciascuna portano un attributo `source` per distinguerle nelle automazioni.

Ogni notifica di allerta include un link alla pagina iLMeteo.it della località. Canali di consegna:

- Una `persistent_notification` viene sempre creata (e rimossa quando l'allerta rientra) — resa con il logo iLMeteo e un link cliccabile nel frontend HA.
- Opzionalmente, push verso uno o più **dispositivi mobili con il companion app** tramite l'opzione `notify_targets` (vuota per impostazione predefinita). Il link iLMeteo è surfacciato come bottone d'azione tappable ("Apri iLMeteo.it") poiché il push nativo non renderizza il Markdown. Sono supportati solo i target `notify.mobile_app_*` — le nuove entità notify (HA 2026.5+) non supportano ancora il payload dati del companion app.
- Un evento `ilmeteo_weather_alert` viene sparato ad ogni nuova allerta, cambio di severità o rientro (`alert_id`, `severity`, `kind`, `title`, `message`, `source`, `link`, `cleared`), per costruire automazioni personalizzate.

Le allerte vengono deduplicate per `alert_id` + severità e persistite attraverso i riavvii, quindi ricevi una notifica solo quando un'allerta compare per la prima volta o peggiora, non ad ogni refresh di 30 minuti.

## Dati esposti

**Condizioni attuali** *(box tempo reale)*: `temperature`, `humidity`, `wind_speed`, `wind_bearing`, `condition`

**Previsione giornaliera** *(box riepilogo giornaliero ufficiale)*: temperatura max/min, **probabilità di precipitazioni**, vento, condizione, più quantità totale di precipitazioni (dal box orario)

**Previsione oraria** *(box triorario)*: per ogni slot di 3 ore → temperatura, temperatura percepita, umidità, vento, precipitazioni, condizione

---

## Sviluppo e test

Il parser HTML è isolato in `api.py` (`parse_box`) senza dipendenze da Home Assistant, quindi può essere testato direttamente:

```bash
python tests/test_parser.py
```

I test usano fixture HTML reali in `tests/fixtures/`.

I provider di allerta (`alerts.py`) sono anch'essi privi di dipendenze da Home Assistant — `HeuristicAlertProvider` è puro, e `DpcSensorAlertProvider` richiede solo `hass.states.get()`, sostituito con un fake minimale:

```bash
python tests/test_alerts.py
```

`IlMeteoAlertManager` (dedup/persistenza/dispatch notifiche in `alert_manager.py`) non è coperto qui — importa `homeassistant.core`/`homeassistant.helpers.storage` direttamente, quindi richiederebbe `pytest-homeassistant-custom-component` invece di questo setup senza dipendenze.

Per rigenerare il dataset delle località dai file CSV ufficiali di iLMeteo:

```bash
python scripts/build_locations.py codici_comuni.csv codici_province.csv \
  custom_components/ilmeteo/data/locations.json.gz
```

---

## Changelog

Vedi [CHANGELOG.md](https://github.com/giorgioparri/ha-ilmeteo/blob/HEAD/CHANGELOG.md) per la cronologia completa delle versioni.

---

## Licenza

Apache-2.0 — vedi [LICENSE](https://github.com/giorgioparri/ha-ilmeteo/blob/HEAD/LICENSE)

## Disclaimer

Questo è un progetto non ufficiale, non affiliato con, approvato da o supportato da iLMeteo Srl. I dati meteo vengono recuperati dal box di previsione pubblico di iLMeteo.it. Usare a proprio rischio e in conformità con i [termini di utilizzo](https://www.ilmeteo.it/portale/termini_e_condizioni) di iLMeteo.

## Ringraziamenti

Built with the assistance of [Claude](https://claude.ai) by Anthropic.
