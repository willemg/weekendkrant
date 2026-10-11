# Weekendkrant Ingress

Niet-geheime Weekendkrant-broncode wordt uitsluitend in `willemg/weekendkrant`
onderhouden. ChatGPT Sites is deployment/runtime, geen alternatieve source of
truth. Wijzigingen moeten eerst via een GitHub-PR gereviewd en gemerged worden;
publicatie van die gereviewde versie naar de bestaande ChatGPT Site is een
afzonderlijke stap. Deze feature-PR wijzigt of publiceert de actieve Site niet.
Er is geen automatische deploymentflow ingericht.

## Vijf MCP-tools

| Tool | Input | Compact succesresultaat |
| --- | --- | --- |
| `submit_weekendkrant_fiche` | Willekeurig top-level JSON-object | `status`, `queue_item_id` |
| `start_sherlock_run` | `{}` | `status`, `run_id`, `topic` |
| `filter_sherlock_sources` | `urls`: maximaal 50 strings | `status`, `unreviewed` |
| `record_sherlock_source` | `run_id`, `topic`, `url`, `outcome`, `rationale`; optioneel `title` (string/null) | `status`, `canonical_url` |
| `finish_sherlock_run` | `run_id`, `status` (`completed`/`failed`) | `status`, `run_id`, `run_status` |

`status` in succesresultaten is `success`. De backend kiest bij start atomair het
volgende topic (1, 2 of 3); de plugin kiest nooit zelf een topic. Run-IDs zijn
positieve safe integers. De vier Sherlock-inputschemas weigeren extra velden.

Filtering leest uitsluitend de registratie van concrete gereviewde pagina-URLs:
geen reservering, registratie of story-deduplicatie. De plugin canonicaliseert
geen URLs. Registreer een bron uitsluitend na inhoudelijke review van de concrete
pagina, nooit voor zoekresultaten, snippets of ongeopende/gefilterde kandidaten.
`outcome` en `rationale` zijn compacte controleerbare auditnotities, geen private
reasoning/chain-of-thought. Finish sluit de run definitief af.

De filtertool is read-only; de overige vier tools wijzigen backendstate. Alle
calls vereisen de bestaande `oai-authenticated-user-id`-header. De MCP-handler
biedt exact deze vijf tools en weigert onbekende toolnamen met een JSON-RPC-error.

## Discovery en HTTP

De vaste discoverypointer is
`https://raw.githubusercontent.com/willemg/weekendkrant/main/config/ingress-endpoint.json`.
Alleen `https://<single-label>.trycloudflare.com/ingress` wordt geaccepteerd:
geen credentials, expliciete poort (ook niet `:443`), query of fragment. De plugin
bouwt sibling endpoints met `URL` op dezelfde gevalideerde host:

- `/ingress`
- `/sherlock/runs`
- `/sherlock/sources/filter`
- `/sherlock/sources`
- `/sherlock/runs/finish`

Callers kunnen geen host of backendpad kiezen. Alle POSTs gebruiken uitsluitend
`WEEKENDKRANT_INGRESS_TOKEN`. Sites beheert de echte waarde buiten deze bron.
Discovery ontvangt geen bearer-token. Redirects staan uit, timeouts zijn 10 s
voor discovery en 15 s voor de backend; er zijn geen retries of secretlogs.

Succesresponses worden gevalideerd en teruggebracht tot bovenstaande velden.
Errors zijn uitsluitend `{status: "error", code: "..."}`; upstreambodies en
netwerkdetails worden nooit doorgestuurd. Sherlock-calls onderscheiden onder meer
400 (`invalid_request`), 401 (`authentication_refused`), 409 (`conflict`),
413 (`payload_too_large`), 5xx (`backend_server_error`), redirects,
netwerkfouten en ongeldige responses. De fichetool behoudt zijn bestaande
succescontract en foutcodes voor compatibiliteit.

## Historische baseline

De oorspronkelijke import kwam uit Sites-broncommit
`816da26fa0a32c432b0b8e661d7414cd24f711b2`, gekoppeld aan gepubliceerde versie 1
van project `appgprj_6ac67c60766481918cc9c32316c3d8ac`.
`README.sites-original.md` bewaart de oorspronkelijke README byte-for-byte;
de historische statusmeldingen daarin zijn geen actuele operationele instructies.

`worker/index.js` bevat de tools, schemas, MCP-handler en gedeelde HTTP-client.
`tests/bridge.test.js` gebruikt uitsluitend gemockte responses en een fictieve
secret. `.openai/hosting.json` bevat het niet-geheime project-ID en capability.
Sites beheert overige deployment-, plugin- en toegangsmetadata buiten deze bron.

## Lokaal testen en bouwen

Gebruik Node.js 22 of nieuwer. Geen dependencies, echte secret of netwerk nodig:

```sh
npm --prefix plugin/weekendkrant_ingress test
npm --prefix plugin/weekendkrant_ingress run build
```

Tests dekken de bestaande fichetool, strikte discovery, vijf toolschemas en
annotations, exacte authenticated POSTs, input- en responsevalidatie, foutmapping,
secretbescherming en MCP-dispatch. De build kopieert worker en hostingmanifest
naar `dist/server/index.js` en `dist/.openai/hosting.json`. Deze lokale buildoutput
wordt niet gecommit en het buildcommando publiceert niets.
