# Partieformular → PGN (partieformular-demo)

Interaktive Streamlit-Demo der [Sebastians Spielwiese](https://sebastians-spielwiese.net/) (Schach-Linie, Demo C). Du schreibst die Züge eines Turnier-Partieformulars ab, die App liest jede Zelle tolerant,
spielt die Partie nach, **prüft jeden Zug gegen die Schachregeln**, markiert **unklare Stellen**, begründet **Regelverstöße** und erzeugt ein **PGN** für die Datenbank.
Nacharbeit ist ausdrücklich vorgesehen: Jede Entscheidung steht als Text in der Zelle, nicht in einem versteckten Zustand.

Live: [spielwiese-partieformular.streamlit.app](https://spielwiese-partieformular.streamlit.app/)

Lauffähig mit: `streamlit run app.py`

## Was die Demo zeigt

* **Formular erfassen:** Kopfdaten (Namen, Ergebnis, Turnier, Ort, Datum, Runde, Elo) und eine Tabelle Zug für Zug (Weiß, Schwarz) oder Text einfügen (auch ein ganzes PGN). Ein Foto oder Scan kann daneben liegen und im Tab „Foto lesen“ von einem Erkenner gelesen werden (Gerüst, siehe unten).
* **Prüfung:** Jede Zelle bekommt einen Status: in Ordnung, bereinigt (genau ein Zug passt, die Schreibweise wurde geglättet), unklar, Regelverstoß oder nicht prüfbar (hinter einem Regelverstoß).
  Dazu eine Meldung zu jedem Fund, eine Tabelle mit Farben und, bei jeder Problemstelle, das Brett vor dem Zug mit den Kandidaten als Pfeilen.
* **Nacharbeit:** Vorschläge übernehmen (der Zug wird in der Schreibweise des Formulars in die Zelle geschrieben, auf einem deutschen Formular also mit S, L, T, D), die Zelle selbst ändern, einen legalen Zug aus der Liste wählen, bei einem Zug nach dem Ende die Zellen leeren.
* **Nachspielen:** Schieberegler über die Partie mit Brett und FEN, zum Abgleich mit dem Formular.
* **PGN:** sieben Pflichtzeilen in Standardreihenfolge, Zugnummern, Zeilen bis 80 Zeichen, Bewertungszeichen als NAG. Ist alles geklärt: das PGN. Sonst die Wahl zwischen einem Teil-PGN (nur gesicherte Züge) und einem vorläufigen PGN (gewählte Vorschläge, unklare Stellen als Kommentar).
* **Sechs Beispielformulare** in der Seitenleiste, je eines pro Fall (siehe Tabelle unten).

## Wie die App eine Zelle liest und entscheidet

1. **Lesen** (`pf_notation.py`): deutsche und englische Figurenbuchstaben, ausführliche Schreibweise (`e2-e4`), Schlagzeichen `x` und `:`, Rochade mit Nullen oder O, Umwandlung mit und ohne `=`, Schach- und Mattzeichen, Bewertungszeichen, Figurensymbole, Zugnummer im Feld, Ergebnis in einer Zelle. Ein `?` mitten im Zug ist ein unleserliches Zeichen (`S?3`, `Sf?`, `?`).
2. **Abgleichen** (`pf_pruefung.py`): Alle legalen Züge der Stellung, die zu den lesbaren Zeichen passen. Zuerst streng (das Schlagzeichen stimmt), sonst ohne Rücksicht auf das Schlagzeichen (Hinweis).
3. **Entscheiden:**
   * genau ein Zug: in Ordnung oder bereinigt;
   * mehrere Züge, fehlende Umwandlungsfigur, unleserliches Zeichen, leere Zelle zwischen Zügen: **unklar**. Die App spielt für jeden Kandidaten den **Rest der Partie** nach und zählt, wie viele Folgezellen danach noch eindeutig und legal sind (ein abgeschriebenes Schach- oder Mattzeichen muss stimmen). Der Kandidat mit der längsten Fortsetzung wird vorläufig gewählt; ein Gleichstand wird als Gleichstand gemeldet;
   * kein Zug passt: **Regelverstoß** mit Begründung (gefesselt, Weg versperrt, Zug gehört dem Gegner, Rochaderecht verfallen, kein Schlag möglich und so weiter), ähnliche legale Züge (höchstens eine Abweichung in Figur, Ziellinie, Zielreihe oder angegebenem Ausgangsfeld) und eine Suche nach einer **früheren Ursache** in den zehn Halbzügen davor (zwei Abweichungen erlaubt).
4. **Partieende:** Nach Matt, Patt oder wenn kein Matt mehr möglich ist, darf kein Zug folgen. Fünfmal dieselbe Stellung und 75 Züge ohne Bauernzug und Schlag beenden die Partie nach FIDE-Regeln von selbst; die App warnt dann.
5. **Ergebnis:** Matt, Patt und das Ergebnis im Kopf müssen zusammenpassen; Aufgabe, Zeit oder Vereinbarung sind aus den Zügen nicht prüfbar und werden nur vermerkt.

Die **Schachregeln sind ein eigener, kleiner Zuggenerator** (`pf_brett.py`, nur Standardbibliothek). python-chess (GPL) wird nur in den Tests und der Messung benutzt, nicht in der App.

## Beispielformulare

Der Fall, den jedes Beispiel zeigt, und was die Prüfung daraus macht (Zählung aller Halbzüge; `tests/test_beispiele.py` und `tests/test_claims.py` rechnen es bei jedem Lauf neu):

| Beispiel | Fall | Halbzüge | ok | bereinigt | unklar | Regelverstoß | nicht prüfbar |
|---|---|---|---|---|---|---|---|
| Saubere Partie | Opernpartie (Morphy, Paris 1858) in deutscher Schreibweise, alles in Ordnung | 33 | 33 | 0 | 0 | 0 | 0 |
| Unscharf geschrieben | dieselbe Partie mit `e2-e4`, `d:e5`, fehlendem x und +, und `Sd7` bei zwei Springern | 33 | 24 | 8 | 1 | 0 | 0 |
| Unleserliches Zeichen | Légals Mattfalle mit `Lg?`, `L?7+` und einem ganz unleserlichen 4. Zug von Schwarz | 13 | 10 | 0 | 3 | 0 | 0 |
| Regelverstoß | 3. Zug von Schwarz lässt den König im Schach | 6 | 5 | 0 | 0 | 1 | 0 |
| Fehler früher | `0-0` statt `0-0-0` im 12. Zug, der Verstoß zeigt sich erst im 13. | 33 | 24 | 0 | 0 | 1 | 8 |
| Zug nach dem Matt | nach dem Matt von Schwarz steht noch ein Zug | 5 | 4 | 0 | 0 | 1 | 0 |

## Befunde (alle Zahlen: diese Messung, siehe unten)

**Wie gut löst die App Unklarheiten auf?** `tools/messung.py` nimmt 300 Zufallspartien (Zufalls-Seeds 0 bis 299, mindestens 24 Halbzüge, python-chess würfelt legale Züge, Bauernzüge bevorzugt), stört **je Partie eine Stelle** und vergleicht mit dem wahren Zug.
Die Tabellen und `data/messung.json` entstehen aus demselben Lauf; `tests/test_claims.py` liest die Tabellen aus der Datei neu und sucht sie zeilenweise hier.

*Drei Störungen, die „unklar“ ergeben:*

| Störung | Versuche | als unklar erkannt | Spitze ohne Gleichstand | davon: erster Kandidat ist der wahre Zug | Gleichstand an der Spitze | Kandidaten im Gleichstand (Mittel) | wahrer Zug unter den Kandidaten |
|---|---|---|---|---|---|---|---|
| Zusatz weggelassen (`Nbd7` → `Nd7`) | 173 | 173 | 134 (77,5 %) | 134 von 134 | 39 (22,5 %) | 2,0 | 173 (100,0 %) |
| ein Zeichen durch `?` ersetzt | 299 | 299 | 271 (90,6 %) | 271 von 271 | 28 (9,4 %) | 2,4 | 299 (100,0 %) |
| Zelle leer gelassen | 300 | 300 | 177 (59,0 %) | 177 von 177 | 123 (41,0 %) | 5,0 | 283 (94,3 %) |

*Heißt:* Wenn die Fortsetzung einen Kandidaten klar vorn sieht, war er in diesen Messungen jedes Mal der wahre Zug. Bei einem Gleichstand entscheiden die Regeln allein nichts, und das sagt die App.
Voraussetzung: **eine einzige Störung** je Partie und sonst eine regelkonforme Abschrift. Bei einer leeren Zelle zeigt die App höchstens acht Kandidaten; in den 17 Fällen ohne den wahren Zug standen mehr als acht zur Wahl. Für das „?“-Zeichen entfallen 175 der 299 Fälle auf genau einen passenden Zug (Zeile „eindeutig“ der Messung).

*Regelverstöße:*

| Störung | Versuche | erkannt | Anmerkung |
|---|---|---|---|
| erfundene Figur-Feld-Angabe, die nicht geht | 300 | 300 (100,0 %) als Regelverstoß | alle 462 Vorschläge sind legale Züge |
| Ziellinie eines wahren Zugs um eins verschoben | 162 | 133 (82,1 %) als Regelverstoß | in allen 133 steht der wahre Zug unter den Vorschlägen; in den übrigen 29 war der verschobene Zug selbst legal und ist nicht erkennbar |
| früherer Zug durch einen anderen legalen Zug derselben Figurenart ersetzt | 278 | 241 (86,7 %) später als Regelverstoß, davon 184 (76,3 %) höchstens 10 Halbzüge nach der Ursache | in 168 dieser 184 (91,3 %) nennt die App die frühere Zelle mit dem wahren Zug |

Die Rückwärtssuche sieht nur zehn Halbzüge zurück; 57 der 241 Verstöße zeigten sich später und werden nur als Verstoß gemeldet, ohne die frühere Ursache. Das ist eine Grenze der Demo, kein Fehler der Messung.

**Wie gut sind die Schachregeln selbst?** Der Zuggenerator zählt die bekannten Perft-Werte (Zahl der Stellungen nach n Halbzügen aus sechs Standardstellungen; die Werte sind die veröffentlichten Referenzwerte, nicht python-chess):

| Stellung | Tiefe 1 | Tiefe 2 | Tiefe 3 |
|---|---|---|---|
| Grundstellung | 20 | 400 | 8.902 |
| Kiwipete | 48 | 2.039 | 97.862 |
| Stellung 3 | 14 | 191 | 2.812 |
| Stellung 4 | 6 | 264 | 9.467 |
| Stellung 5 | 44 | 1.486 | 62.379 |
| Stellung 6 | 46 | 2.079 | 89.890 |

Dazu in den Tests (`tests/test_brett.py`, `tests/test_pruefung.py`), gegen python-chess: Zuglisten, SAN, FEN, Schach, Matt, Patt, zu wenig Material und Stellungswiederholung in Zufallspartien; für jede Figur und jedes Feld, ob ein legaler Zug passt; Rochade und en passant an ausgewählten Stellungen;
Partien in deutscher und englischer Schreibweise werden ohne Befund gelesen und das PGN liest python-chess ohne Fehler zurück.

## Foto lesen (Gerüst)

Im Tab „Foto lesen“ findet die App das Raster des Formulars selbst, und ein Erkenner liest jede beschriebene Zelle. Das Raster lässt sich von Hand nachstellen (Ausschnitt, Drehung, Zeilen, Blöcke, Spaltenbreiten).
**Datenschutz beim Foto:** Die Foto-Auswahl erscheint erst, wenn Du bestätigst, dass Du die Namen schwärzt oder die Spieler einverstanden sind. Die Datei wird nur in Deinem Browser gelesen (Komponente `pf_schwaerzen.py` mit `pf_schwaerzen_frontend/index.html`, reines HTML und JavaScript): Du ziehst schwarze Rechtecke über Namen und kannst die obere Zone schwärzen. Erst nach „Übernehmen“ geht ein **neu gezeichnetes JPEG** (ohne Dateiname und Aufnahmedaten, längste Seite höchstens 2200 Pixel) an den Server, auf dem die App läuft (öffentliche Fassung: Streamlit Community Cloud). Dort liegt es nur für die Sitzung im Arbeitsspeicher (`st.session_state`, kein sitzungsübergreifender Cache; `tests/test_app.py` prüft das). Die App speichert es nicht und gibt es nicht weiter. Ob alle Namen geschwärzt sind, kann die App nicht erkennen: Das prüfst Du selbst. Die Pixel des gesendeten Bildes wurden im Browser nachgemessen (obere Zone und Markierungen schwarz, der Rest unverändert); `tests/test_schwaerzen.py` prüft den Wert der Komponente und dass die Frontend-Datei nichts nach außen sendet. Für den Betrieb der Plattform gilt deren Datenschutzerklärung.

Der Weg vom Bild zum Zug hat zwei Teile, die in der Prüfung zusammenlaufen:

* **Text:** Das gierige Ergebnis des Erkenners, unsichere Zeichen (Sicherheit unter 0,6) als `?`. Der Text läuft wie abgetippter Text durch Lese- und Prüfregeln, also mit den Jokern und dem Fortsetzungstest von oben.
* **Bildwahrscheinlichkeit:** Für jeden legalen Zug der Stellung rechnet die App aus, wie wahrscheinlich das Zellbild genau diese Zeichenfolge zeigt (CTC-Vorwärtsverfahren auf der Ausgabe des Erkenners, die Schreibweisen mit und ohne Schlag- und Schachzeichen addiert),
  und normiert über die legalen Züge. Sie ordnet Kandidaten bei Gleichstand der Fortsetzung, schlägt bei einem nicht legalen Text die Züge vor, die dem Bild am ehesten entsprechen (die Prüfung läuft damit vorläufig weiter, die Zelle steht als „unklar“ da),
  und meldet Zweifel, wenn ein legaler Zug zum Text passt, aber ein anderer dem Bild fast ebenso gut entspricht.
  Hat der Mensch eine Zelle geändert, gilt seine Entscheidung und das Bild wird nicht mehr dagegen gehalten.

**Hilft ein allgemeines Handschriftmodell?** Gemessen mit TrOCR-small-handwritten (Microsoft, MIT, ONNX-Gewichte von Xenova, 87 und 159 MB, `tools/trocr_messung.py`, ohne PyTorch). TrOCR bewertet wie das Schach-Modell Kandidaten: log P(Kandidat | Zellbild) im Entschlüsseler mit vorgegebener Zeichenfolge.
Aufgabe: der wahre Zug gegen die sieben ähnlichsten anderen Beschriftungen des Datensatzes (kleinster Editierabstand), 100 Zugbilder; Zufall wäre 1 von 8, also 12 Treffer. Zahlen in `data/trocr_messung.json`.

| Bewertung | wahrer Zug vorn |
|---|---|
| Schach-Modell (Trainingsdaten, also optimistisch) | 92 von 100 |
| TrOCR, Bild auf 384×384 gestaucht (üblich) | 15 von 100 |
| TrOCR, Seitenverhältnis erhalten | 11 von 100 |
| Schach-Modell plus 0,3 × TrOCR | 92 von 100 |

TrOCR liegt auf dem Niveau des Zufalls, und die Kombination ändert nichts. Die Anbindung stimmt: Gerenderter englischer Text („Mr. Brown commented icily.“) liest TrOCR richtig; Schachnotation (`Nxe5+`) kennt es nicht. Ohne Nachtraining auf Schachzüge hilft das allgemeine Modell bei den unsicheren Zellen also nicht.
Ein Feintuning wäre der nächste Schritt gewesen; das spezialisierte Modell ist inzwischen nachtrainiert (siehe unten), TrOCR wurde nicht nachtrainiert.

**Und ein freies, kleines OCR-Modell?** Gemessen mit GLM-OCR (zai-org, 0,9 Milliarden Parameter, MIT-Lizenz, läuft lokal auf der GPU, `tools/ocr_messung.py`; derzeit eines der stärksten kleinen Dokument-OCR-Modelle), gleiche Blätter und gleiches Raster wie oben (262 Halbzüge, die ersten 20 Blätter, jede Zelle einzeln gelesen,
Ausgabe bereinigt: Zugnummer weg, Malzeichen zu x, Groß- und Kleinschreibung der Felder). Zahlen in `data/ocr_messung_*.json`.

| Leser | Text allein richtig | mit Regelprüfung richtig |
|---|---|---|
| Schach-Modell (Trainingsdaten, also optimistisch) | 234 (89,3 %) | 161 (61,5 %) |
| GLM-OCR, ganze Zelle | 80 (30,5 %) | 36 (13,7 %) |
| GLM-OCR, auf die Schrift zugeschnitten | 82 (31,3 %) | 43 (16,4 %) |

An den 300 Zugbildern des Datensatzes liest GLM-OCR 115 (38,3 %) ganz richtig, die Zeichenfehlerrate liegt bei 47 %.
In den ersten zwölf Proben fielen auf: `g` als `9` („Ng4“ → „N94“), `b` als `6`, `a` als `0` (nicht im ganzen Satz ausgewertet). Ein Allgemein-OCR-Modell kennt Schachnotation nicht und nutzt keinen Zeichensatz mit nur 28 Zeichen; ohne Nachtraining ist es für diese Aufgabe deutlich schlechter als das Schach-Modell, obwohl das auf HCS im Vorteil ist.
Das Modell gibt außerdem nur Text aus, keine Wahrscheinlichkeiten: Die Bewertung der legalen Züge gegen das Bild fällt weg.

**Raster und Perspektive** (`pf_entzerren.py`, nur numpy und Pillow, kein Erkenner nötig): Ein gedrucktes Formular hat viele gleich weit entfernte Linien. Die App markiert dunklere Punkte als ihre Umgebung (unabhängig von der Beleuchtung) und lässt sie auf Geraden abstimmen (Hough-Verfahren),
getrennt für die linke und die rechte Bildhälfte, weil die Blöcke gegeneinander verschoben sein können. Die längste Folge gleichmäßig verteilter Linien ist das Zeilenraster (30 Zeilen, also 31 Linien; fehlt am Rand eine, wird sie ergänzt, am oberen Bildrand auch bei nur teilweise sichtbarer erster Zeile).
Die äußeren senkrechten Linien zwischen oberster und unterster Zeilenlinie ergeben mit ihnen die vier Ecken der Tabelle; daraus entsteht die Entzerrung (Perspektivtransformation). Im entzerrten Bild liegen die senkrechten Linien aufrecht, ihre Spitzen ergeben Blöcke und Spaltenbreiten
(die Vorlage: Weiß und Schwarz teilen sich den Rest hinter der schmalen Nummernspalte, Weiß|Schwarz liegt in der Blockmitte). Das Verfahren setzt gedruckte Zeilenlinien voraus; ohne sie meldet die App, dass sie nichts gefunden hat, und bleibt bei der Einstellung von Hand.
Ob die erste Zeile im Raster wirklich Zug 1 ist, kann die App nicht wissen: Eine um eine Zeile verschobene Lage liest lauter gültige Züge. Deshalb zeigt die Vorschau das Raster, und die Hinweise nennen ergänzte Linien.

**Nachtraining für deutsche Buchstaben und fremde Schreiber** (`training/`, PyTorch auf der GPU, Zahlen in `data/nachtraining.json`). Das Original kennt nur englische Notation (28 Klassen) und hat alle HCS-Blätter gesehen, seine 89,3 % sind für fremde Schreiber also zu gut.
Das Modell der App ist deshalb nachtrainiert: 32 Klassen (dazu S, L, T, D), dieselbe Architektur, **von Zufallsgewichten aus** trainiert (nicht vom Original aus, damit die Messung sauber bleibt), nach Blättern getrennt gemessen.
Die 195 Blätter mit sauber gefundenem Raster (12.822 Zellen) wurden nach Blatt geteilt: 156 Blätter (10.517 Zellen) zum Training, 39 Blätter (2.305 Zellen) nur zur Prüfung. Prüfmengen, die kein Modell im Training sah:

* **echt, englisch:** echte Zellen der 39 Prüfblätter;
* **deutsch eingesetzt:** echte Bauernzüge der Prüfblätter, vor die Feldangabe ist eine Handschrift-Glyphe (S, L, T oder D, aus EMNIST, getrennte Prüfglyphen) gesetzt, aus „f3“ wird „Sf3“. Das ist keine echte deutsche Handschrift;
* **gerendert, unbekannte Schriften:** 3.000 Zellen aus echten Lichess-Partien (Oktober 2026), in vier Schriften gerendert, die im Training fehlten.

Anteil der Zellen, die ganz richtig gelesen werden (gieriger Text), nach 120 Epochen:

| Rezept | echt, englisch | deutsch eingesetzt | gerendert, unbekannte Schriften |
|---|---|---|---|
| A: nur echte Zellen, leichte Verfremdung | 55,5 % | 0,0 % | 19,5 % |
| C: starke Verfremdung, deutsche Varianten und 12.000 gerenderte Zellen je Epoche | 56,9 % | 73,4 % | 92,5 % |

Nach 30 Epochen lagen beide bei 43 % (echt): Mehr Epochen helfen noch, auch A, das auf den Trainingsdaten überlernt. Starke Verfremdung allein (Rezept B) lernt langsamer (11,2 % nach 30 Epochen); der Gewinn von C kommt aus den gerenderten und den deutschen Zellen.
**Grenzen:** Auf Blättern fremder Schreiber liest das beste Modell nur etwa 6 von 10 Zellen ganz richtig (Zeichenfehlerrate 29,6 %). Echte deutsche Ligabögen kennt es nicht; die 73,4 % beschreiben eingesetzte Buchstaben, nicht echte Handschrift.
Das Modell kennt Zellen so, wie die App sie aus einem Blatt schneidet; die fertig zugeschnittenen Einzelzellen des Datensatzes (anderer Zuschnitt) liest es deutlich schlechter als das Original. Für die App zählt der Weg vom Blatt, deshalb misst `tools/messung_hcs.py zellen` weiter das Original.

**Kalibrierung und Test-Time-Augmentation.** Das Modell war überzuversichtlich. Die Temperatur T = 1,8 (auf einer Hälfte der Prüfblätter gewählt, auf der anderen gemessen) senkt die negative Log-Wahrscheinlichkeit der richtigen Beschriftung je Zelle von 6,04 auf 4,19.
Sie steckt in der ONNX-Datei, die Zeichen-Wahrscheinlichkeiten und die Schwelle für „?“ (0,6) haben dadurch eine Bedeutung: Bei Lesungen mit Zuversicht ab 0,9 (19,4 % der Zellen) stimmt der gelesene Text in 90,7 % der Fälle, ab 0,97 (6,5 % der Zellen) in 97,2 %.
Liest die App jede Zelle fünfmal (verschoben und gestreckt) und mittelt die Wahrscheinlichkeiten, steigt die Trefferquote auf echten Zellen von 56,9 % auf 58,1 % und auf den deutschen von 73,4 % auf 74,2 %; die Lesezeit je Zelle verfünffacht sich, die App tut das beim Lesen, nicht bei der Rastersuche.

**Das Modell der App** ist Rezept C mit 120 Epochen, aber auf **allen** 195 Blättern trainiert (also auch den 39 Prüfblättern), damit es mehr Schreiber kennt. Seine Zahlen auf den Prüfblättern sind deshalb nicht mehr ungesehen und stehen hier nicht; als ehrliche Schätzung für fremde Schreiber gelten die 56,9 % des Laufs ohne die Prüfblätter.

**Modell und Daten** (beides nicht im Repo; die Download-Quellen und Prüfsummen stehen in `pf_erkenner.py`):

* Modell der App: Architektur „chess-ocr-bilstm“ von Gerhard Trippen auf Hugging Face (MIT): CNN, BiLSTM und CTC, nachtrainiert (siehe oben), 43.276.402 Bytes als ONNX, Eingabe 64×256 Pixel in Graustufen, 32 Klassen (K Q R B N, a bis h, 1 bis 8, x + # = O -, dazu S L T D).
  Die App lädt es auf Knopfdruck und prüft Größe und SHA-256. Das Original (43.266.310 Bytes, 28 Klassen, laut Modellkarte 82,9 % der Züge ganz richtig) ist nur noch für die Vergleichsmessungen in `tools/` im Einsatz.
* Datensatz HCS (Handwritten Chess Scoresheet; Eicher, Farmer, Li, Majid), Apache-2.0, Spiegel `BenjaminKost/processed_hcs` (13.731 Zugbilder mit Beschriftung) und `unprocessed_hcs` (206 ganze Blätter mit Zugliste). Der Originalserver (tc11.cvc.uab.es) war beim Download nicht erreichbar.

**Befund zu den Daten:** Die Beschriftungen der ganzen Blätter geben wieder, was auf dem Blatt steht, auch Fehler und Kritzel. Als Schachpartie gelesen sind nur 10 von 206 Blättern vollständig regelkonform,
und der regelkonforme Anfang aller Blätter umfasst 3.351 von 13.735 Halbzügen (24,4 %). Messungen am ganzen Blatt zählen deshalb nur den regelkonformen Anfang (`tools/messung_hcs.py`); die Zahlen stehen in `data/hcs_beschriftungen.json`, `data/hcs_messung_*.json`.

**Was getestet ist und was nicht:**

* Getestet (`tests/test_ctc.py`, `test_raster.py`, `test_lesen.py`): die CTC-Rechnung gegen eine Brute-Force-Summe über alle Ausrichtungen; Rasterschnitt, Einrasten, Geraderichten und Modelleingabe an selbst gezeichneten Formularen; die Dekodierung gegen die Regeln mit einem **simulierten Erkenner**
  (Verwechslungen und unsichere Zeichen nach einer Verwechslungstabelle); der Ablauf in der App. Mit dem simulierten Erkenner liest die Prüfung mit Bildwahrscheinlichkeit deutlich mehr Züge richtig als der Text allein; das prüft die Dekodierung, **nicht** die Güte eines Handschriftmodells, und echte Lesefehler sind stärker gebündelt als simulierte.
* **Nicht gemessen:** die Güte auf Deinen Formularen. Die Messung unten nutzt Blätter, aus denen das Modell selbst trainiert wurde, und sagt deshalb nur, dass der Ablauf mit dem echten Modell funktioniert.

**Messung mit dem Original-Modell** (`tools/messung_hcs.py`, onnxruntime 1.32.0; Zahlen in `data/hcs_messung_zellen.json` und `data/hcs_messung_blaetter.json`).
Vorbehalt vorweg: HCS ist der Trainingsdatensatz dieses Modells, die Zahlen sind deshalb zu gut für fremde Formulare. Die Modellkarte nennt auf ihrem Prüfanteil 82,9 %.

* **Zugbilder:** die ersten 300 Zellen des Datensatzes, gieriger Text gegen die Beschriftung: 99,3 % der Zellen ganz richtig, Zeichenfehlerrate 0,22 %.
* **Ganze Blätter:** die ersten 60 Blätter, gezählt nur am regelkonformen Anfang der Beschriftung (814 Halbzüge; dahinter ist die Beschriftung selbst fehlerhaft), Raster und Perspektive automatisch aus den gedruckten Linien bestimmt (siehe oben, ohne den Erkenner):

| Auswertung | richtig | stille Fehler | unklar | nicht prüfbar |
|---|---|---|---|---|
| Text des Erkenners allein | 718 (88,2 %) | | | |
| Text mit Regelprüfung | 548 (67,3 %) | 17 (2,1 %) | 22 | 233 |
| Text mit Regelprüfung und Bildwahrscheinlichkeit | 704 (86,5 %) | 27 (3,3 %) | 113 | 0 |

„Richtig“ heißt: Der Zug nach der Prüfung (bei „unklar“ der vorläufig gewählte) ist der der Beschriftung, ohne Schach- und Mattzeichen verglichen. „Stille Fehler“ sind Zellen, die als in Ordnung dastehen und falsch sind.
Die Regelprüfung allein verliert hier Züge, weil ein Lesefehler die Prüfung abbricht (233 nicht prüfbar). Mit der Bildwahrscheinlichkeit läuft sie ohne Abbruch durch (0 nicht prüfbar), dafür stehen mehr Zellen als „unklar“ zur Bestätigung da.
Der Text des Erkenners allein trifft hier etwas mehr Züge als die Prüfung mit Bild; die Prüfung legt dafür die unsicheren Stellen zur Bestätigung vor. Ob die als „unklar“ vorgelegten Zellen gerade die falschen sind und woher die etwas höheren stillen Fehler mit Bild kommen, habe ich nicht ausgewertet.

**Raster im Vergleich** (dieselben ersten 20 Blätter, 262 Halbzüge, Text des Erkenners allein richtig):

| Rasterlage | richtig |
|---|---|
| feste Voreinstellung (Oberkante und Unterkante geraten) | 103 (39,3 %) |
| mit dem Erkenner gesucht (Oberkante und Unterkante, Drehung geschätzt) | 207 (79,0 %) |
| automatisch aus den gedruckten Linien, entzerrt | 234 (89,3 %) |

Das Raster ist der empfindlichste Teil: Mit der alten Voreinstellung lag nur etwa jede dritte Zelle richtig, mit der automatischen Lage fast neun von zehn.

* Offen: Nachtraining an echten deutschen Ligabögen und an Deiner Handschrift; Raster für Formulare ohne gedruckte Zeilenlinien (dort bleibt die Suche mit dem Erkenner und die Einstellung von Hand).

## Bewusst nicht enthalten

* **Verlässlich Handschrift lesen.** „Foto lesen“ ist ein Gerüst mit einem kleinen Modell: Auf Blättern fremder Schreiber liest es etwa 6 von 10 Zellen ganz richtig, und echte deutsche Ligabögen hat es nie gesehen (deutsche Buchstaben kennt es aus eingesetzten Handschrift-Buchstaben und Schriften). Wie gut es auf Deinen Formularen liest, ist nicht gemessen. Das Raster findet die App nur bei gedruckten Zeilenlinien.
* **Varianten, Kommentare, Uhrzeiten** des Formulars. Text mit Klammern wird gelesen, die Klammern gehen verloren (mit Hinweis).
* **Andere Ausgangsstellungen:** nur die normale Grundstellung, kein Schach960, keine Partie ab FEN.
* **Mehrere Fehler auf einmal.** Die Auflösung der Unklarheiten ist für eine einzelne Störung gemessen. Gibt es mehrere, stehen die Kandidaten trotzdem da, aber die Fortsetzung kann sich an einer zweiten Störung totlaufen; ein Regelverstoß stoppt die Prüfung, bis er behoben ist.
* **Remis auf Antrag** (dreifache Wiederholung, 50 Züge) wird nur beim Abgleich mit dem Ergebnis erwähnt.
* **PGN in ChessBase und Scid geöffnet:** nicht geprüft. Das PGN ist UTF-8 und wird in den Tests von python-chess gelesen.

## Tests

`python -m pytest tests/` (Test-venv mit `requirements-dev.txt`; `chess` nur für die Orakel-Tests):

* `test_brett.py`: Perft, Zufallspartien Zug für Zug gegen python-chess, Sonderfälle (Rochade, en passant, Umwandlung, Matt), zu wenig Material, Wiederholung, SAN.
* `test_notation.py`: jede in der App genannte Schreibweise, Joker, Ergebnisse, Unlesbares.
* `test_pruefung.py`: Zufallspartien als Formular, Störungen, erfundene Züge, Begründungen, Fortsetzungstest, frühere Ursache.
* `test_pgn.py`: Datum, Kopf, Zeilenumbruch, NAG, Text zu Zellen, Rundlauf.
* `test_beispiele.py`: jedes Beispiel zeigt seinen Fall; `test_claims.py`: jede Zahl dieser README.
* `test_ctc.py`, `test_raster.py`, `test_entzerren.py`, `test_lesen.py`: Foto lesen (siehe dort).
* `test_app.py`: AppTest (Beispiele, Vorschläge übernehmen, Tabelle bearbeiten über den Widget-Zustand, Text einfügen, Upload nur nach Bestätigung, kein Bild-Cache); `test_schwaerzen.py`: Wert der Schwärzen-Komponente, Rahmen der Frontend-Datei; `test_modul_frisch.py`: geänderte Hilfsmodule werden nach einem Update neu geladen (`modul_frisch.py`, siehe unten); `test_runtime_imports.py`: Laufzeitpakete in `requirements.txt`, kein python-chess in der App.

## Dateien

`app.py` (Oberfläche) · `pf_brett.py` (Schachregeln) · `pf_notation.py` (Zelle lesen) · `pf_pruefung.py` (Auflösung, Begründung, Partieprüfung) · `pf_pgn.py` (Kopf, PGN, Text zu Zellen) · `pf_logik.py` (Zellen ändern, Export wählen) ·
`pf_schwaerzen.py` (Foto im Browser wählen und Namen schwärzen) · `modul_frisch.py` (lädt geänderte Hilfsmodule nach einem Update neu; die Streamlit Community Cloud behält sie sonst bis zum Neustart der App) · `pf_constants.py` (Beispiele, Texte) · `pf_ansicht.py` (Brett als SVG) · `pf_pieces.py` (Figuren) · `pf_raster.py` (Foto in Zellen), `pf_entzerren.py` (Raster finden, Perspektive), `pf_ctc.py` (CTC-Rechnung), `pf_erkenner.py` (ONNX-Modell, Simulation), `pf_lesen.py` (Foto lesen, Bildwahrscheinlichkeit) · `tools/messung.py`, `tools/zufall.py`, `tools/messung_hcs.py`, `tools/trocr_messung.py`, `tools/ocr_messung.py` (Messungen) · `data/messung.json`, `data/messung_stichprobe.json`, `data/hcs_beschriftungen.json`, `data/hcs_messung_*.json`.

## Quellen und Lizenzen

* **Partien der Beispiele:** die Opernpartie (Morphy gegen Herzog Karl von Braunschweig und Graf Isouard, Paris 1858) und Légals Mattfalle (1750) sind gemeinfreie Lehrpartien; die Züge werden in den Tests mit python-chess nachgespielt. Die übrigen Beispiele sind Eigenbau.
* **Figuren:** Satz „cburnett“ von Colin M. L. Burnett (Wikimedia Commons, BSD-Lizenz), Pfade aus `chess.svg` von python-chess, wie in den anderen Spielwiese-Demos.
* **python-chess** (GPL-3.0 oder neuer) läuft nur in Tests und Messung. Eine Lizenz für den Code dieser Demo ist noch nicht festgelegt.
