# Weekendkrant Ingress

Deze map is de canonieke bronkopie in GitHub van de ChatGPT Site/MCP-plugin
**Weekendkrant Ingress**. De actieve deployment loopt nog via ChatGPT Sites.
Deze source-import wijzigt of publiceert de Site niet. Toekomstige wijzigingen
moeten eerst via een GitHub-PR gereviewd worden. Er is hiermee geen automatische
deploymentflow ingericht.

## Herkomst en exacte baseline

Geïmporteerd uit Sites-broncommit
`816da26fa0a32c432b0b8e661d7414cd24f711b2`, gekoppeld aan gepubliceerde versie 1
van project `appgprj_6ac67c60766481918cc9c32316c3d8ac`.
De publicatiestatus van die versie is gecontroleerd als `succeeded`.

De eerste importcommit neemt alle zeven getrackte bestanden byte-for-byte over,
met alleen het nieuwe bovenliggende pad `plugin/weekendkrant_ingress/`.
In de volgende documentatiecommit is deze README vervangen; de oorspronkelijke
README blijft byte-for-byte beschikbaar als `README.sites-original.md`.
De historische statusmeldingen in die oorspronkelijke README zijn geen actuele
operationele instructies. Implementatie, tests, manifest en buildscript zijn
ongewijzigd; er zijn geen aanpassingen aan imports of testharness nodig.

| Oorspronkelijk bestand | Inhoud |
| --- | --- |
| `.gitignore` | Negeert buildoutput, env-bestanden en lokale Sites-runtimegegevens. |
| `.openai/hosting.json` | Niet-geheim project-ID en MCP-capability. |
| `README.md` | Oorspronkelijke toelichting, hier bewaard als `README.sites-original.md`. |
| `package.json` | Dependencyvrij ESM-project met test- en buildcommando. |
| `scripts/build.mjs` | Kopieert worker en hostingmanifest naar `dist/`. |
| `tests/bridge.test.js` | Zes lokale tests met fictieve secret en gemockte HTTP-responses. |
| `worker/index.js` | Tool/schema, MCP-handler, discovery, URL-validatie, POST-client, foutafhandeling en HTML-pagina. |

`worker/index.js` exporteert `TOOL` voor `submit_weekendkrant_fiche`, `DISCOVERY`,
`endpoint()` en `submit()`. De default worker handelt `/mcp` af en levert op andere
paden de zichtbare HTML-pagina. Er bestaan geen aparte pagina-, tooldefinitie- of
HTTP-clientbestanden in de oorspronkelijke bron.

De discoverypointer is
`https://raw.githubusercontent.com/willemg/weekendkrant/main/config/ingress-endpoint.json`.
`endpoint()` controleert HTTPS, een enkel subdomein onder `trycloudflare.com` en
de afwezigheid van credentials, een niet-standaardpoort en fragment. De huidige
code dwingt het pad `/ingress` of de afwezigheid van een query niet af; dit is een
inventarisatie van de bestaande implementatie, geen validatiefix.

## Secret en Sites-metadata

Alleen de environment-secretnaam `WEEKENDKRANT_INGRESS_TOKEN` wordt gebruikt.
Sites beheert de echte waarde buiten deze bron; die is niet geëxporteerd of
gekopieerd. De waarde `fictional-test-only` in de tests is uitsluitend testdata.

Project-/versie-/deploymentrecords, pluginregistratie, toegangsinstellingen en
runtime-secretbeheer zijn Sites-metadata, geen aanvullende gewone bronbestanden.
Het project-ID en de capability hebben wel een bronrepresentatie in het manifest.
De build genereert `dist/server/index.js` en `dist/.openai/hosting.json`; deze zijn
kopieën van de bronbestanden en worden niet meegecommit. Git-metadata wordt niet
geïmporteerd. Er is geen nieuwe deploymentmethode toegevoegd.

## Lokaal testen

Gebruik Node.js 22 of nieuwer (geverifieerd met Node.js 24.19.0). Geen
pakketinstallatie, echte secret of netwerkverbinding is nodig:

```sh
npm --prefix plugin/weekendkrant_ingress test
npm --prefix plugin/weekendkrant_ingress run build
```

Er zijn exact **zes** tests in `tests/bridge.test.js`:

1. `exactly one write tool, arbitrary object schema`
2. `endpoint restrictions`
3. `missing, unreachable and invalid discovery`
4. `payload cannot choose destination, POST body exact, redirects disabled`
5. `compact errors and no secret echo`
6. `unauthenticated MCP write denied`

De tests injecteren een mock-fetcher in `submit()`; de MCP-test voor een
ongeauthenticeerde write stopt vóór netwerktoegang. Beide commando's hierboven
werken vanuit de repositoryroot. Het buildcommando genereert alleen lokale
bestanden en publiceert niets.
