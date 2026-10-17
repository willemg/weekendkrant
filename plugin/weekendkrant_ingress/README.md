# Weekendkrant Ingress

Fase 7: de startketen gebruikt nu de [algemene dispatcher](../../docs/dispatcher.md), met ready-first
selectie, persistente pause en globale/rolconcurrency. `start_weekendkrant_executor`
meldt de executor zonder argumenten aan; `/executor/start` is canoniek en de oude
`/executor/sherlock/start`-route blijft alias. Schema 10 bewaart generieke immutable
activationreceipts en behoudt alle schema-9-audit. Alleen Sherlock is geregistreerd;
geen Leonardo-jobs of verwerking van offers. Deze bronwijziging is geen deployment.
De onderstaande fase-5-beschrijving blijft van toepassing op Sherlock-opdrachten.

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
| `finish_weekendkrant_job` | claim-ID/token, `status` (`succeeded`/`failed`/`uncertain`), `output_refs`; optioneel `error` | Job/attempt-ID en `job_status` |
| `abandon_weekendkrant_job` | claim-ID/token, `error` | Job/attempt-ID en `job_status: blocked` |

Strikte velden en begrensde teksten/referenties; de plugin controleert ook
response-identiteiten. Alle vier wijzigen private jobstate (validate kan expiry
vastleggen) en publiceren niets. De metadata-audit geldt voor alle vier hints:

| Tool | readOnlyHint | destructiveHint | idempotentHint | openWorldHint |
| --- | --- | --- | --- | --- |
| `claim_weekendkrant_job` | false | true | true | false |
| `validate_weekendkrant_claim` | false | true | true | false |
| `finish_weekendkrant_job` | false | true | true | false |
| `abandon_weekendkrant_job` | false | true | true | false |

- `readOnlyHint=false`: claim schrijft een attempt/receipt; finish en abandon
  sluiten bestaande attempts af. Ook validate kan persistent expiry vastleggen.
- `destructiveHint=true`: finish maakt succeeded/failed terminaal; abandon
  sluit de attempt als uncertain en blokkeert de job. **Alle vier**, inclusief
  claim en validate, voeren eerst de expiryquarantaine uit: verlopen running
  attempts worden expired en hun jobs blocked, ook buiten de aangeleverde job
  en bij een geweigerde operatie of receipt-replay. Dit is geen louter additieve write.
- `idempotentHint=true`: exacte claim/finish/abandon-retries met dezelfde
  operation-ID en argumenten gebruiken persistente receipts. Validate herhaalt
  dezelfde actuele controle zonder extra attempt of resultaat; expiry is een
  herhaalbare lifecycle-overgang. Een voortschrijdende backendklok kan het
  antwoord en de expiryquarantaine veranderen; de hint belooft geen vast antwoord.
- `openWorldHint=false`: effecten blijven binnen de private Weekendkrant-state.
  De vaste discovery en backend zijn transport binnen deze begrensde dienst;
  input-/outputreferenties worden niet bezocht en er is geen externe publicatie.

`tests/bridge.test.js` controleert per tool via `tools/list` exact het volledige
annotations-object, net als voor de vijf bestaande tools.
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

De functionele minimumversie voor tests en build is **Node.js 18.3.0**.
`package.json` legt dit vast met `engines.node`. De gebruikte features bepalen
deze grens:

| Feature | Beschikbaarheid / bewijs |
| --- | --- |
| `fetch`, `Request`, `Response` zonder extra flags | Vanaf Node 18.0.0 standaard aanwezig ([Node 18-aankondiging](https://nodejs.org/en/blog/announcements/v18-release-announce)) |
| `node:test` en `node --test` | Testmodule vanaf 18.0.0; CLI-flag vanaf 18.1.0 ([CLI-documentatie](https://nodejs.org/api/cli.html#--test)) |
| `Response.json()` | Ontbreekt in echte Node 18.2.0; aanwezig in 18.3.0. De pluginchecks zijn op 18.3.0 gecontroleerd. Node 18.3.0 bundelt Undici 5.4.0 ([release](https://nodejs.org/en/blog/release/v18.3.0)). Dit is de bepalende ondergrens. |
| `AbortSignal.timeout()`, `Object.hasOwn`, ES modules/top-level await, `node:fs/promises` | Beschikbaar vóór 18.3.0; de concrete test/buildpaden zijn op 18.3.0 gecontroleerd. |

Dit is een featureminimum, geen eis dat de test-runner- of fetch-API destijds al
als stabiel gemarkeerd was, en geen versiecontract voor de gehoste worker.
`npm test` en `npm run build` draaien vooraf `scripts/check-runtime.mjs`.
De expliciete plugin-developmenttest met Python-backendfixture gebruikt dezelfde
preflight vóór tijdelijke database/server worden gestart: een ontbrekende/te oude Node of uitgeschakelde fetch-feature geeft
een concrete fout, geen stille skip. Er zijn geen Node-packageafhankelijkheden,
echte secrets of extern netwerk nodig om de tests/build uit te voeren:

```sh
npm --prefix plugin/weekendkrant_ingress test
npm --prefix plugin/weekendkrant_ingress run build
```

Tests dekken de bestaande fichetool, strikte discovery, negen toolschemas en
annotations, exacte authenticated POSTs, input- en responsevalidatie, foutmapping,
secretbescherming en MCP-dispatch. De build kopieert worker en hostingmanifest
naar `dist/server/index.js` en `dist/.openai/hosting.json`. Deze lokale buildoutput
wordt niet gecommit en het buildcommando publiceert niets.


### Optionele bridge/backend-developmenttest

Start deze test expliciet in een plugin-developmentomgeving met Node.js >=18.3.0
én Python 3.9+ (de fixture gebruikt alleen de standaardbibliotheek):

```sh
npm --prefix plugin/weekendkrant_ingress run test:backend
```

Of gebruik vanuit de repositoryroot een expliciete Python-interpreter:

```sh
.venv/bin/python plugin/weekendkrant_ingress/tests/bridge_backend.py
```

Deze test bewaart de echte JavaScript-brug → HTTP → SQLite-dekking van operation-ID
replay en verloren claim-/finishantwoorden na commit. Hij staat buiten de gewone
Python-testdiscovery en buiten `npm test`; de opdracht is uitsluitend voor plugin-
development, niet voor bibib. `./start_tests.sh` en de Python-systeemgate op bibib
blijven volledig Node-vrij. De backend/Python-tests bewijzen hun eigen persistente
replay-/idempotentiecontract; de werkelijk gepubliceerde Sites-route wordt apart
bewezen door de bestaande deployment-smoke.


## Fase 9.5: server-owned bootstrap

`start_weekendkrant_executor()` → `POST /executor/start` accepteert een leeg
object en retourneert uitsluitend executor_id of null. Caller-generated
operation_id, activation_id, timestamps en andere velden worden lokaal én door
de backend geweigerd. Omitted MCP arguments worden een leeg object.

`get_weekendkrant_job(executor_id)` → `POST /executor/job` leest alleen het
gebonden pakket met claim, rol/input/resultaat en immutable contractsnapshots.
Geen productie, selectie of nieuwe attempt. Claimtoken komt uit attemptstate,
nooit uit receipts. De generieke bridge kent geen rollenlijst of rolvertakking.

Scheduled finish/abandon geven claim-ID/token en hun resultaatvelden mee zonder
operation_id. Bibib bepaalt één terminale identiteit per attempt; gewijzigde
retries conflicteren, ook bij een wissel tussen finish en abandon. Exacte retry
is veilig na een verloren antwoord. Het model herstart geen inhoudelijk werk.
De expliciete operator-control-plane kan optioneel zijn bestaande operation_id
meegeven; dat hoort niet bij het scheduled contract.

Het canonieke runtime-artifact is
[executor/instructions.md](../../executor/instructions.md).
Geen publicatie of live instructiewijziging vanuit deze PR.

Pluginchecks: `./start_tests.sh --plugin` vanuit de repositoryroot, in de
pluginontwikkelomgeving met Node. De standaard `./start_tests.sh` blijft
uitsluitend de Node-vrije Python-fast-track draaien.

## Leonardo historical recall (fase 9.6)

Nieuwe tool `recall_weekendkrant_part` → `POST /jobs/leonardo-recall`, met exact
`job_id`, `attempt_id`, `token`, `ref` en `recall_id`. De backend autoriseert onder
actuele lease uitsluitend vorige processed_refs plus nieuwe assignmentrefs uit
hetzelfde immutable dossiercontract. Topicgelijkheid verleent geen leesrecht.
Reconstructie gebruikt het bestaande revision/source-archief; geen externe URLs,
nieuwe jobs of bronkopieën. De response bevat `ref`, `sha256`, `content`, `bytes`
en lokale `cl100k_base`-`tokens`, plus MCP `status:success`.

Metadata: `readOnlyHint:false` vanwege append-only recallaudit,
`destructiveHint:false`, `idempotentHint:true`, `openWorldHint:false`.
Inhoud, provenance en lifecycle blijven read-only; geen indirecte expirywrites.
Een retry gebruikt dezelfde attempt-lokale recall_id en ref, telt geen tweede
logische read en valideert altijd opnieuw de actuele claim. Gewijzigde ref onder
dezelfde identiteit conflicteert; een gesloten/verlopen claim krijgt geen replay.
Geen claimtokens of bronbytes in audit. Compacte backendfouten blijven de bestaande
`conflict`/`invalid_request`/`backend_server_error`-mapping gebruiken.

Schema 12 verruimt de Leonardo-startinput en begrenst startinput plus cumulatieve
unieke recalls per attempt technisch op 1.048.576 lokale tokens / 8 MiB UTF-8;
geen providercontextclaim of kostenoptimum. State-output blijft 4K / 32.768 bytes.
Zie [het volledige runtimecontract](../../docs/leonardo-state.md#historical-recall-fase-96).
Backend/schema en Sites-publicatie zijn aparte invoerstappen; deze fase voert ze
niet uit. Validatie in de pluginlaag: `./start_tests.sh --plugin`, inclusief
exacte tools/list-annotations, request/responsevalidatie en echte recall door
MCP → HTTP → SQLite → generieke statefinish. De normale fast-track blijft Node-vrij.


## Fase 12: afzonderlijke missies en Kuifje-fiches

Geen nieuwe tools: finish_weekendkrant_job accepteert optioneel kuifje_missions
naast leonardo_state, of kuifje_result voor een Kuifje-job. De backend valideert
rol, frozen contract, provenance, budget, fencing en atomaire opslag.
submit_weekendkrant_fiche accepteert Kuifjes mission_id, stabiele fiche_id en
claim als transportmetadata zonder Sherlock-run_id. De inhoud blijft schema v1;
exacte mission/fiche/payload-retries zijn idempotent zolang de claim geldig is.
De algemene fichetool behoudt idempotentHint=false wegens legacy-/Sherlockgedrag.
De generieke executor en jobophaling veranderen niet.
Zie [backendcontract en invoering](../../docs/phase-12-kuifje.md).
