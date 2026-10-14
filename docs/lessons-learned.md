# Technisch leerlog

Compact log van incidenten, verkeerde aannames en blijvende ontwikkelregels.
Voeg bij een nieuw incident een concrete observatie en afdwingingsplek toe;
onderscheid waargenomen gedrag van een nog onbewezen oorzaak.

## Groene tests, kapotte echte keten (13 oktober 2026)

- **Incident:** unit- en integratietests waren groen terwijl de echte Sherlock →
  ingress → SQLite → Ariadne-keten na een grote wijziging niet bruikbaar was.
- **Aanname:** losse groene componenttests bewezen dat het geheel bleef werken.
- **Werkelijkheid:** lokale componenttests dekten de volledige keten en de
  werkelijk gepubliceerde externe route onvoldoende af.
- **Les:** maak beide grenzen afzonderlijk reproduceerbaar en controleerbaar.
- **Blijvende regel:** na ketenwijzigingen bewijst de geïsoleerde systeemtest
  ingress → SQLite → Ariadne → part/revision → processed; de deployment-smoke
  bewijst gepubliceerde Sites → tunnel → productie-ingress → persistente
  fichewrite. Samen vormen ze de operationele gate. Latere verwerking van het
  productie-item is aanvullende observatie, geen verplichte smoke-wachttijd.
- **Afgedwongen in:** [systeemtest](../tests/test_system_e2e.py),
  [operationele gate](daily-runtime.md#systeemtest-en-operationele-gate) en
  [deploymentprocedure](plugin-deployment.md). De echte smoke is een afzonderlijke
  operationele check, geen automatisch bewijs uit de lokale suite.

## Sporadische MCP safety-blocks (12 oktober 2026)

- **Incident:** identieke calls met dezelfde zichtbare argumenten bereikten
  afwisselend wel en niet de backend; blokkeringen traden vóór de backend op.
- **Aanname:** een geweigerde call wees op een fout in payload of backend.
- **Werkelijkheid:** de zichtbare observaties verklaren het platformcriterium
  niet. Er is geen bewezen causaal verband met metadata of descriptions.
- **Les:** houd het publieke toolcontract exact en bewaar reproduceerbaar bewijs;
  presenteer een metadatafix of succesvolle retry niet als bewezen oorzaak/oplossing.
- **Blijvende regel:** audit alle vier annotations en descriptions tegen werkelijk
  gedrag, inclusief indirecte writes zoals expiry. Test de volledige annotations
  via `tools/list`. Onderscheid expliciete safety-blocks, backendfouten en onzekere
  writes; verander payloads niet om blokkeringen te omzeilen.
- **Afgedwongen in:** [toolmetadata/descriptions](../plugin/weekendkrant_ingress/worker/index.js),
  [exacte metadata-contracttests](../plugin/weekendkrant_ingress/tests/bridge.test.js),
  [metadata-audit](../plugin/weekendkrant_ingress/README.md#generieke-control-plane-fase-4)
  en [Sherlocks begrensde retry- en bewijsbeleid](agents/sherlock.md#experimentele-retries-bij-platform-safety-blocks).

## Code Mode: maximaal 20 toolcalls per executie (12 oktober 2026)

- **Incident:** van 30 geplande opeenvolgende calls bereikten exact 20 de backend;
  vóór call 21 volgde `Code Mode exceeded the maximum number of tool calls.`
- **Aanname:** één Code Mode-executie kon de volledige reeks afwerken.
- **Werkelijkheid:** de waargenomen grens gold per executie; een grens van 20
  voor de hele Sherlock-run, taak of conversatie is hiermee niet vastgesteld.
- **Les:** verdeel werk in begrensde batches met marge voor overige calls.
- **Blijvende regel:** maximaal 15 toolcalls per Code Mode-executie, inclusief
  alle andere calls. Zet een volgende batch voort met dezelfde run-ID/topic en
  bevestigde voortgang; verlaag de vereiste brondekking niet.
- **Afgedwongen in:** [Sherlocks Code Mode-batching](agents/sherlock.md#code-mode-batching).
  Dit is een executorinstructie; de backend kan het platformbudget niet afdwingen.

## Node bijna een impliciete bibib-dependency (14 oktober 2026, PR #48)

- **Incident:** de JavaScript bridge → HTTP → SQLite-test dreigde Node vereist
  te maken voor de gewone Python-testsuite op bibib.
- **Aanname:** alles in dezelfde repository behoort tot dezelfde runtime/testlaag.
- **Werkelijkheid:** de JavaScript-brug draait op ChatGPT Sites; bibib draait de
  Python-backend en Ariadne. Een repositorygrens is geen runtimegrens.
- **Les:** plaats dependencies en tests bij de laag die ze werkelijk gebruikt.
- **Blijvende regel:** **bibib lean and mean**: alleen productiecomponenten en
  hun noodzakelijke dependencies op bibib. De gewone Python-suite en systeemgate
  blijven Node-vrij; pluginontwikkeling/build en de optionele bridgetest blijven
  afzonderlijk. De echte externe grens blijft bewezen door de deployment-smoke.
- **Afgedwongen in:** [architectuur](architecture.md), [Python-testwrapper](../start_tests.sh),
  [Python-systeemtest](../tests/test_system_e2e.py),
  [afzonderlijke pluginchecks](../plugin/weekendkrant_ingress/README.md#lokaal-testen-en-bouwen)
  en [optionele bridge/backend-test buiten Python-discovery](../plugin/weekendkrant_ingress/tests/bridge_backend.py).
