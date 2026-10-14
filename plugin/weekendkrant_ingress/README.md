# Weekendkrant Ingress

Ontwikkeling en tests gebeuren uitsluitend bij de canonieke GitHub-bron in
`willemg/weekendkrant`. ChatGPT Sites is runtime/deployment, geen ontwikkelbron.
Deployment bestaat uit synchronisatie van één gemergede commit, gevolgd door
publicatie. Zie [het canonieke deploymentdocument](../../docs/plugin-deployment.md)
voor de werkwijze, architecturale motivatie en deploymentidentiteit.

## Bestaande vijf MCP-tools

| Tool | Input | Compact succesresultaat |
| --- | --- | --- |
| `submit_weekendkrant_fiche` | Top-level JSON-object; optioneel positieve safe-integer `run_id` als Sherlock-transportmetadata | `status`, `queue_item_id` |
| `start_sherlock_run` | `{}` | `status`, `run_id`, `topic` |
| `filter_sherlock_sources` | `urls`: maximaal 50 strings | `status`, `unreviewed` |
| `record_sherlock_source` | `run_id`, `topic`, `url`, `outcome`, `rationale`; optioneel `title` (string/null) | `status`, `canonical_url` |
| `finish_sherlock_run` | `run_id`, `status` (`completed`/`failed`) | `status`, `run_id`, `run_status` |

`status` in succesresultaten is `success`. De backend kiest bij start atomair het
volgende topic (1, 2 of 3); de plugin kiest nooit zelf een topic. Run-IDs zijn
positieve safe integers. De vier Sherlock-inputschemas weigeren extra velden.

Sherlock geeft bij fichepublicatie zijn huidige `run_id` mee. De backend vereist
een `running` run met hetzelfde topic en slaat queue-item plus runkoppeling atomisch
op; Ariadne blijft exact vier fichevelden lezen. `run_id` is voor legacy callers
optioneel; historische fiches blijven ongekoppeld. Bij gekoppelde fichecalls zijn
400/409 zichtbaar als `invalid_request`/`conflict`; legacy foutcodes blijven geldig.
Fichepublicatie blijft niet-idempotent, ook met `run_id`. Backend eerst upgraden
naar schema 5 voordat nieuwe plugin/instructies worden geactiveerd; zie
[ingressprovenance en invoering](../../docs/ingress-runtime.md#sherlock-ficheprovenance).

Filtering leest uitsluitend de registratie van concrete gereviewde pagina-URLs:
geen reservering, registratie of story-deduplicatie. De plugin canonicaliseert
geen URLs. Registreer een bron uitsluitend na inhoudelijke review van de concrete
pagina, nooit voor zoekresultaten, snippets of ongeopende/gefilterde kandidaten.
`outcome` en `rationale` zijn compacte controleerbare auditnotities, geen private
reasoning/chain-of-thought. Finish sluit de run definitief af.

De filtertool is read-only; de overige vier tools wijzigen backendstate. Alle
calls vereisen de bestaande `oai-authenticated-user-id`-header. De MCP-handler
behoudt deze vijf tools en voegt vier generieke tools toe. Onbekende toolnamen
geven een JSON-RPC-error.

## Generieke control-plane (fase 4)

| Tool | Input | Compact succesresultaat (naast `status: success`) |
| --- | --- | --- |
| `claim_weekendkrant_job` | `operation_id`, `job_id`, `activation_id` | Claim-ID/token/lease, rol en immutable input/contractrefs; of `claim: null` |
| `validate_weekendkrant_claim` | `job_id`, `attempt_id`, `token` | Job/attempt-ID, `claim_status`, `valid`, `lease_until` |
| `finish_weekendkrant_job` | `operation_id`, claim-ID/token, `status` (`succeeded`/`failed`/`uncertain`), `output_refs`; optioneel `error` | Job/attempt-ID en `job_status` |
| `abandon_weekendkrant_job` | `operation_id`, claim-ID/token, `error` | Job/attempt-ID en `job_status: blocked` |

Strikte velden en begrensde teksten/referenties; de plugin controleert ook
response-identiteiten. Alle vier wijzigen private jobstate (validate kan expiry
vastleggen), zijn idempotent volgens het operatiecontract en publiceren niets.
Gebruik bij transportretry dezelfde operation-ID en exacte argumenten. Dezelfde
activation-ID geldt voor de hele activation, ook na jobfinish. Een oude claimreceipt
is geen nieuwe uitvoeringsbevoegdheid: valideer vóór werk en respecteer de lease.
De control-plane claimt alleen een expliciet job-ID, zonder dispatcher of jobcreate.
Zie [protocol en retries](../../docs/jobs.md#fase-4-protocol-identiteit-en-operation-receipts).

Recovery is uitsluitend een apart backend-operatorendpoint met een afzonderlijk
secret. De plugin heeft geen reconcile-tool en krijgt geen recoverysecret.
Backend/schema 8 moeten vóór import/publicatie van deze pluginversie gereed zijn.
Bestaande Sherlock-instructies gebruiken voorlopig uitsluitend hun huidige tools.

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
- `/jobs/claim`, `/jobs/validate`, `/jobs/finish`, `/jobs/abandon`

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

Tests dekken de bestaande fichetool, strikte discovery, negen toolschemas en
annotations, exacte authenticated POSTs, input- en responsevalidatie, foutmapping,
secretbescherming en MCP-dispatch. De build kopieert worker en hostingmanifest
naar `dist/server/index.js` en `dist/.openai/hosting.json`. Deze lokale buildoutput
wordt niet gecommit en het buildcommando publiceert niets.
