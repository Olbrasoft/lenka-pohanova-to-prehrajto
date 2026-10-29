# Lenka Pohanová → Přehraj.to

Samostatný seriálový uploader pro jediný účet Lenky.
Každá epizoda může mít českou a anglickou variantu. České zdroje přebírá
z `Olbrasoft/sdilej-serialy`; pouze anglické verze dohledává na Sdílej.cz.
Zdrojová videa se proudově přenášejí na Přehraj.to bez ukládání celého videa.
Přihlašovací údaje patří do prostředí nebo GitHub Secrets. Veřejný kód
obsahuje pouze otisk povoleného cílového e-mailu.

## Pojmenování

Název seriálu i epizody se používá v původním jazyce díla. Názvy se
nepřekládají ani neodhadují z názvů souborů. Následuje `S01E01`, dostupný
oficiální původní název epizody, skutečné rozlišení originálu a jazykový dodatek.
U anglických seriálů jsou tedy názvy anglické, u ostatních v jejich původním jazyce.
Pokud původní název epizody po ověření není dostupný, vynechá se.
Nedokončená kontrola nebo technická chyba odloží upload do vyřešení metadat.
Stejně pojmenované seriály se rozlišují rokem, případně katalogovým ID.

| Varianta | Příklad názvu |
| --- | --- |
| Ověřený český zvuk | `The Big Bang Theory S01E01 Pilot 1080p CZ Dabing` |
| Anglický zvuk a potvrzené české titulky | `The Big Bang Theory S01E01 Pilot 1080p CZ Titulky` |
| Anglický zvuk bez českých titulků | `The Big Bang Theory S01E01 Pilot 1080p` |
| Neanglický původní název | `La casa de papel S01E01 Efectuar lo acordado 1440p CZ Dabing` |

Rozlišení je vždy před jazykovým dodatkem: `SD`, `720p`, `1080p`, `1440p`
nebo `4K`, stejně jako v původním seriálovém uploaderu. Přejmenování již
nahraných souborů používá rozměry skutečně přeneseného zdroje, i když se
mezitím ve frontě objevil kvalitnější originál.

Metadata pocházejí z identitou ověřených záznamů TMDB: [vyhledávání seriálů](https://developer.themoviedb.org/reference/search-tv),
[překlady názvů seriálů](https://developer.themoviedb.org/reference/tv-series-translations),
[detail řady](https://developer.themoviedb.org/reference/tv-season-details)
a [překlady názvů epizod](https://developer.themoviedb.org/reference/tv-episode-translations).
Vyhledávání musí vrátit právě jeden seriál se shodným původním názvem;
u neanglických epizod se požaduje výslovný název v původním jazyce.
Starší doložený anglický název je původním názvem pouze u anglického seriálu.
Ověřené výjimky lze zadat do `config/titles.json` ve skupinách `series` a `episodes`.

## České zdroje a pořadí

Import čte katalog, ověřený manifest a uložené fronty obou původních účtů.
Ze všech ověřených zdrojů se vybírá nejvyšší rozlišení a v něm nejmenší soubor.
Zahrnují se i publikovaná vylepšení kvality z původního projektu; dokončený
starší upload nesmí přebít kvalitnější ověřený zdroj.
Importují se pouze skutečně ověřené české zvukové verze s důvěrou alespoň 0,65,
platnými rozměry, délkou, velikostí a stabilním detailovým odkazem.
Z historie jiných účtů se nepřenášejí cílová ID, příznaky nahrání,
rezervace, cookies ani dočasné autorizované adresy.

Další import doplňuje nové epizody a vylepšuje dosud nepřidělené zdroje.
Zdroj již nahraného nebo rezervovaného videa zůstává vázaný na skutečně
přenesený soubor; jeho historie se nepřepisuje nově nalezenou kvalitou.
Jeden zdrojový soubor se nepřiřadí více epizodám. Pořadí se přebírá z
`priority_rank` původního hodnoceného katalogu, tedy z hodnocení a počtu hlasů,
nikoli z počtu přehrání. U stejné epizody má česká varianta přednost.
Anglické vyhledávání zahrnuje pouze epizody s převzatým českým zdrojem.

## Anglické verze a titulky

Kontroluje se přesná identita seriálu a epizody, skutečná délka, rozlišení
a původní soubor. Whisper ověřuje první zvukovou stopu ve třech oddělených
vzorcích; alespoň dva musí jazyk potvrdit s důvěrou 0,65. Druhá anglická stopa
v jinak českém souboru nestačí. Vyhledávají se anglické verze i u seriálů,
jejichž původní jazyk je jiný.

Přednost má nejvyšší skutečné rozlišení, potom nejmenší soubor v této kvalitě.
České titulky rozhodují až při shodě rozlišení i velikosti. Například 4K bez
titulků má přednost před 1080p s titulky; menší 4K bez titulků má přednost
před větším 4K s titulky. Při neúplné kontrole kandidátů se výběr odloží:
neověřený originál může mít vyšší rozlišení nebo menší velikost. Příprava
střídá čtyři nové epizody s jedním starším opakováním kontroly.

Textové české titulky se získávají výhradně z přesného původního souboru
nebo jeho vlastní stránky. Po zpracování videa se připojí, ověří se jejich jazyk
i otisk obsahu v přehrávači a teprve potom se přidá dodatek `CZ Titulky`.
Nejasný výsledek odeslání titulků se pouze kontroluje, nikdy neposílá znovu.
Vypálené titulky ověřuje stejný OCR postup jako u Markéty; OCR nevytváří titulky.
Samostatné obrazové PGS stopy neopravňují k českému titulkovému označení.

## Stav a přenosy

- `variants/cz/manifests/selected-episodes.jsonl`: převzaté české zdroje.
- `variants/en/manifests/selected-episodes.jsonl`: ověřené anglické zdroje.
- `variants/*/state/uploads.json`: vlastní historie každé varianty na účtu Lenky.
- `variants/en/state/discovery.json`: odložené kontroly anglických zdrojů.
- `variants/en/state/subtitles.json`: odeslání a ověření titulků.
- `state/titles.json`: doložené názvy, identifikátory a odložená metadata.

Jeden společný fond má výchozí tři přenosy; `--workers` dovoluje 1 až 6.
České a anglické varianty sdílejí tento limit. Po dokončení úlohy volný worker
převezme další epizodu. Titulkový worker používá vlastní relace a běží na pozadí
po deseti minutách, také během doběhu velkých přenosů.

Před alokací se uloží záměr a po alokaci cílové ID. Přijetí všech bajtů musí
potvrdit uložená HTTP 200/201 účtenka a následná kontrola cílového videa.
Nejistý přenos se znovu nenahrává. Ostatní epizody mohou pokračovat;
nedostupné zdroje mají trvalý časový odstup dalších pokusů.
Stav je vázán na účet Lenky a konkrétní variantu. Jiný účet klient odmítne.

## Lokální použití

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/lenka-sync import --upstream ../sdilej-serialy
.venv/bin/lenka-sync titles --limit 200
.venv/bin/lenka-sync plan --limit 10
.venv/bin/pytest
```

Režim `plan` nepotřebuje přihlašovací údaje a nic nenahrává.
Pro `titles` nastav `TMDB_API_KEY`. Pro vyhledávání anglických zdrojů navíc
nainstaluj `.[discovery]`, FFmpeg a Tesseract s modely `ces` a `eng`.

Přenosové režimy vyžadují `SDILEJ_EMAIL`, `SDILEJ_PASSWORD`,
`PREHRAJTO_EMAIL` a `PREHRAJTO_PASSWORD`.
`prepare` přihlašovací údaje cílového účtu nepotřebuje.
`upload --limit 3` provede jednotlivou dávku; `continuous --runtime-minutes 210`
průběžně vybírá další zdroje. Při `--persist-git-state` musí být nastavený
zapisovatelný remote `origin` s větví `main`; stav se potvrdí v Gitu před přenosem.

## GitHub Actions

- `test`: testy a kontrola kódu při změně.
- `prepare-sources`: hodinový import českých zdrojů, doplnění názvů a příprava anglických verzí.
- `continuous-upload`: hodinový start, nejvýše 210 minut přijímá nové přenosy,
  poté nechá rozběhnuté přenosy doběhnout. Limit runneru je 350 minut.
  Ruční spuštění nabízí `plan`, `upload`, `continuous` a `subtitles`.

Plánované běhy řídí proměnná `AUTOMATION_ENABLED=true`.
Příprava a upload mají oddělené concurrency skupiny a zapisují oddělené soubory.
Všechny uploadovací a titulkové operace sdílejí jednu skupinu bez rušení přenosů.
Uploader načítá průběžně připravované manifesty z Gitu.

Secrets: `SDILEJ_EMAIL`, `SDILEJ_PASSWORD`, `PREHRAJTO_EMAIL`,
`PREHRAJTO_PASSWORD`, `TMDB_API_KEY`. Zdrojový účet musí mít přístup
k originálním rychlým downloadům. Existující účty Pavla, Zdeňka a Markéty
slouží jako zdroj ověřených dat; tento projekt do nich nezapisuje.

Přenosový adaptér vychází ze `sdilej-serialy/continuous.py`, detekce vypálených
titulků a izolovaný Whisper z Markétina projektu. Původ a revize jsou v
`upstream/revisions.json`; ostatní podpůrné moduly používá připnutá závislost.

## Rozlišení jazykových variant a provozní kontrola

Vyhledávání na cíli rozlišuje českou a anglickou variantu stejné epizody.
Samotný název nebo shodné `SxxExx` nepotvrzuje přenos vybraného zdroje.
Dokončení vyžaduje vlastní cílové ID, úplnou přenosovou účtenku a ověření
celého názvu na účtu. Jedno cílové ID nesmí být sdílené českou a anglickou historií.
Neznámé existující video se odloží k prověření, nikoli označí za hotový upload.

`--variant en` umožňuje ověřit samostatnou anglickou dávku. `--variant all`
je výchozí pro průběžný běh a zachovává společný limit přenosů.
V `config/runtime.json` lze nastavit `admit_uploads=false`: worker dokončí
rozběhnuté přenosy a skončí bez přijímání dalších úloh.
Modul `reconcile` uchovává audit oprav starých chybných záznamů a bezpečně
přejmenovává vlastní videa bez opakovaného nahrávání jejich obsahu.
