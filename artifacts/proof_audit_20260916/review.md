# Prüfung der zentralen Doppelleiter-Formel

Datum: 2026-09-16. Geprüft wurden die Definition von D(a,b), die
Hamiltonkreis-Klassifikation und die symbolischen unteren und oberen Schranken
in `paper/sections/{double_ladders,hamiltonian_cycles,exact_hsep}.tex`.
Die Hashes der geprüften Dateien stehen in `results.json`.

## Urteil und Reichweite

Die zentrale Formel

    hsep(D(a,b)) = ((a+2)(b+2)-1)/2, für ungerade a,b >= 3,

lässt sich durch das unten ausgeführte allgemeine Argument begründen. Bei der
Prüfung der Packung und der acht Signaturfälle wurde kein Fehler gefunden.
Die vorliegende Klassifikationsbegründung enthält allerdings zwei sachlich
unzutreffende Formulierungen. Sie sind lokal korrigierbar; weder die
Zyklenklassifikation noch die beiden Zertifikatskonstruktionen müssen dafür
geändert werden.

Dies ist eine argumentbasierte mathematische Prüfung mit zusätzlichen
unabhängigen endlichen Kontrollen, keine maschinenformal verifizierte Beweisdatei
und kein externes Fachgutachten. Nicht geprüft wurden die globale
Extremaluntersuchung, Neuheit, die externen Zertifikatspakete oder sämtliche
zusätzlichen Lift-Behauptungen. Die Manuskriptdateien wurden nicht verändert.

## Zwei Korrekturen am Beweistext

1. `hamiltonian_cycles.tex:29`: Aus den Anschlussbits und der Differenzrekurrenz
   folgt nicht, dass bereits jede Sprosse festliegt. Sind alle Anschlüsse
   ausgewählt, haben sowohl R als auch sämtliche T(i,j) dieselben Anschlussbits
   und überall Schienendifferenz null, aber unterschiedliche Sprossen.
   Richtig ist: Die Differenzen liegen fest; erst nach Wahl der Schienen sind
   die Sprossen durch die Gradgleichungen bestimmt. Bei Differenz +1 oder -1
   liegen auch die binären Schienenwerte unmittelbar fest. Beim Wert null ist
   die anschließende Zusammenhangsanalyse erforderlich.

2. `hamiltonian_cycles.tex:43-44`: Die beiden übrigen Wörter mit genau zwei
   Anschlüssen, 1001 und 0110, erzeugen nicht erst einen vorzeitig geschlossenen
   Bestandteil. Für ungerade Leiterlänge verletzen sie bereits die notwendigen
   Gradgleichungen an den Enden. Sie können daher nicht einmal einen
   aufspannenden 2-Faktor ergeben. Die präzise Ausschlussrechnung folgt unten.

## Allgemeine Rekonstruktion der Zyklenklassifikation

Eine Leiter der Länge m hat Schienenvariablen x[t,s] für 0 <= t < m,
Sprossenvariablen y[t] für 0 <= t <= m und Anschlussbits c[0,s], c[m,s].
Die notwendigen Gradgleichungen sind

    x[0,s] + y[0] + c[0,s] = 2,
    x[t-1,s] + x[t,s] + y[t] = 2   (0 < t < m),
    x[m-1,s] + y[m] + c[m,s] = 2.

Mit d[t] = x[t,0]-x[t,1] folgt

    d[0] = c[0,1]-c[0,0],
    d[t] = -d[t-1],
    d[m-1] = c[m,1]-c[m,0].

Für ungerades m ist m-1 gerade. Somit gilt notwendig

    c[0,0]-c[0,1] = c[m,0]-c[m,1].

Der Schnitt zwischen den beiden Leitern wird von einem Hamiltonkreis positiv
und gerade oft durchquert. Von den vier Verbindungskanten werden daher genau
zwei oder alle vier verwendet.

### Vier Verbindungskanten

Alle Anschlussbits sind eins. Deshalb d[t]=0 und
x[t,0]=x[t,1]=z[t]. Die Sprossen sind nun

    y[0]=1-z[0], y[m]=1-z[m-1],
    y[t]=2-z[t-1]-z[t]  (0<t<m).

Zwei benachbarte Nullwerte von z wären unmöglich, da die gemeinsame Sprosse
Wert 2 haben müsste. Zwischen zwei aufeinanderfolgenden Nullpositionen liegt
ein von den übrigen Knoten abgetrennter Kreis: Die Schienen dazwischen sind
alle vorhanden, die beiden abschließenden Sprossen ebenfalls. Ein Hamiltonkreis
erlaubt daher höchstens eine Nullposition pro Leiter.

Ohne Nullposition besteht die Leiter aus ihren beiden durchgehenden Schienen.
Mit genau einer Nullposition besteht sie aus zwei U-förmigen Wegen, je einem
an jedem Ende. Die Anschluss-Paarungen lauten in der Reihenfolge der vier
Verbindungskanten des Manuskripts:

| Leiterzustand | Paarung |
|---|---|
| A durchgehend | 13 / 24 |
| A mit einer Wendestelle | 12 / 34 |
| B durchgehend | 12 / 34 |
| B mit einer Wendestelle | 13 / 24 |

Unterschiedliche Paarungen auf den beiden Leitern ergeben einen einzigen
Kreis; gleiche Paarungen ergeben zwei Komponenten. Deshalb müssen beide
Leitern durchgehend sein oder beide eine Wendestelle haben. Das ergibt R
und genau die ab verschiedenen Kreise T(i,j).

### Zwei Verbindungskanten

Die Wörter 1001 und 0110 haben auf Leiter A entgegengesetzte
Anschlussdifferenzen an den beiden Enden und sind nach obiger Gleichung
unmöglich. Es bleiben:

| Wort | Leiter A | Leiter B |
|---|---|---|
| 0011 | alle Schienen, nur Sprosse 0 | alle Sprossen, alternierende Schienen |
| 1100 | alle Schienen, nur Sprosse a | alle Sprossen, alternierende Schienen |
| 0101 | alle Sprossen, alternierende Schienen | alle Schienen, nur Sprosse 0 |
| 1010 | alle Sprossen, alternierende Schienen | alle Schienen, nur Sprosse b |

Bei der alternierenden Leiter erzwingt d[t]=+1 oder -1 jede Schiene. Alle
Sprossen haben Wert eins, und es entsteht ein einziger aufspannender Weg
zwischen den beiden ausgewählten Anschlüssen.

Bei der anderen Leiter liegen beide ausgewählten Anschlüsse an demselben
Ende. Am anschlusslosen Ende erzwingt die Gradgleichung beide Schienen und
die End-Sprosse. Gäbe es eine Nullposition der Schienen, würde bereits der
Abschnitt vom anschlusslosen Ende bis zur ersten Nullposition einen isolierten
Kreis bilden. Daher sind alle Schienen vorhanden und nur die Sprosse am
anschlusslosen Ende ausgewählt. Auch diese Leiter bildet einen aufspannenden
Weg. Die zwei Verbindungskanten verbinden die beiden Wege zu genau einem
Hamiltonkreis.

Damit gibt es exakt ab+5 Hamiltonkreise für alle Parameter des Satzes.

## Untere Schranke

Die Inzidenzen der so klassifizierten Kreise ergeben die im Manuskript
aufgeführten Unterstützungen:

- Vier Anforderungen isolieren einzeln die vier Ausnahme-Kreise.
- Die 2a+2b-4 Randanforderungen isolieren die Rand-Wendekreise. Die angegebenen
  Paritäten der ausgeschlossenen Schiene schließen jeweils die Ausnahme-Kreise
  aus; die Seitenkonvention stimmt mit der Reihenfolge der Verbindungskanten
  überein.
- Eine innere Sprosse von A, zusammen mit einer ausgeschlossenen Schiene von B
  in Zelle j, wird genau von T(p-1,j) und T(p,j) erfüllt. Beide Schienenseiten
  sind zulässig. Entsprechend gilt die vertauschte Aussage.

Das innere Wendegitter hat ungerade Seitenlängen a-2 und b-2. Nach Entfernung
der Ecke (a-2,b-2) lassen sich die ersten a-3 Zeilen paarweise und die
verbleibende Zeile spaltenweise mit Domino-Steinen belegen. Für a=3 oder b=3
sind die entsprechenden Paarungsbereiche leer; die Konstruktion bleibt gültig.
Bei a=b=3 bleibt nach Entfernung der einzigen inneren Zelle kein Domino übrig.

Die Unterstützungen der gewählten Anforderungen sind paarweise disjunkt.
Ausgelassen werden genau R und der entfernte Wendekreis. Daher deckt jeder
Hamiltonkreis höchstens eine Packungsanforderung. Ihre Anzahl beträgt

    4 + (2a+2b-4) + ((a-2)(b-2)-1)/2
      = ((a+2)(b+2)-1)/2.

Dies ist eine allgemeine untere Schranke, unabhängig von einer Optimierung.

## Obere Schranke

Die gewählte Familie enthält alle vier Ausnahme-Kreise, alle Rand-Wendekreise
und die inneren Wendekreise mit ungeradem i+j. Ihr Umfang stimmt mit der
Packungsgröße überein. Die Signaturen im Manuskript entsprechen den oben
hergeleiteten Kreisen. Die acht Fälle decken sämtliche verschiedenen
Kantenpaare ab:

1. Zwei Verbindungskanten haben unterschiedliche Ausnahme-Signaturen gleicher
   Größe zwei, also Zeugen in beiden Richtungen.
2. Verbindungskante/Schiene: Ein Rand-Wendekreis in der ausgelassenen Zeile
   oder Spalte liefert die eine Richtung; eine der beiden gegenüberliegenden
   Leiter-Ausnahmen der Schiene die andere.
3. Verbindungskante/Sprosse: Außerhalb der höchstens zwei Nachbarzellen der
   Sprosse existiert wegen Leiterlänge >=3 eine Randzelle. Für die Gegenrichtung
   enthält die Sprosse beide eigenen Leiter-Ausnahmen, die Verbindung nur eine.
4. Zwei Schienen derselben Zelle unterscheiden sich in den alternierenden
   Ausnahmen. Für verschiedene Zellen derselben Leiter liefern die beiden
   ausgelassenen Zeilen beziehungsweise Spalten Randzeugen. Bei verschiedenen
   Leitern existiert je ein Randpunkt in der einen ausgelassenen Linie außerhalb
   der anderen.
5. Zwei Sprossen derselben Leiter: Nicht geschachtelte Nachbarschaften haben
   jeweils eine Zelle in ihrer Mengendifferenz und damit Randzeugen. Die einzigen
   geschachtelten Paare sind End-Sprosse/unmittelbar benachbarte innere Sprosse;
   dort liefert die zusätzliche Ausnahme der End-Sprosse die fehlende Richtung.
6. Zwei Sprossen verschiedener Leitern: Jede enthält beide eigenen Ausnahmen;
   die andere Sprosse enthält davon höchstens eine. Das genügt in beiden
   Richtungen, auch für zwei End-Sprossen.
7. Schiene/Sprosse derselben Leiter: Die Schiene enthält zwei gegenüberliegende
   und eine eigene Ausnahme; die Sprosse enthält zwei eigene und höchstens eine
   gegenüberliegende. Es gibt jeweils eine Ausnahme nur auf einer Seite.
8. Schiene/Sprosse verschiedener Leitern: Eine Randzeile außerhalb der
   Schienenzeile und eine Randspalte außerhalb der Sprossennachbarschaft ergeben
   den Schienen-Zeugen. Der umgekehrte Zeuge liegt in der Schienenzeile und in
   der Sprossennachbarschaft: Bei innerer Zeile und innerer Sprosse enthält das
   Paar aufeinanderfolgender Spalten genau eine Spalte der ausgewählten Parität.
   Die Randfälle sind durch die vollständig ausgewählten Randlinien abgedeckt.

Damit sind die Signaturen paarweise unvergleichbar. Obere und untere Schranke
stimmen überein und ergeben die Formel.

## Unabhängige endliche Prüfungen

`verify_formula.py` importiert ausschließlich die Python-Standardbibliothek.
Es baut D(a,b) direkt aus der Definition und verwendet keine Projekt-Solver,
keine vorhandenen symbolischen Inzidenzfunktionen und keine externen Datenpakete.

- Für alle 25 geordneten Paare a,b in {3,5,7,9,11} werden alle perfekten
  Matchings durch vollständige Rekursion auf den ungematchten Knoten enumeriert.
  Ihre Komplemente werden auf Grad zwei und Zusammenhang geprüft. Die gesamte
  so gefundene Hamiltonkreis-Menge stimmt jeweils mit der Klassifikation überein.
  Diese Enumeration benutzt die Klassifikation nicht zum Beschneiden der Suche.
- Für diese 25 Fälle werden die explizite obere Familie und die Packung gegen
  die vollständig enumerierten Universen geprüft. Damit sind auch die
  jeweiligen graphenspezifischen Optimalwerte unabhängig nachgeprüft.
- Für alle 100 geordneten Paare a,b in {3,5,...,21} werden die vorhergesagten
  Kreise auf dem Graphen überprüft, sämtliche Unterstützungsformeln getestet,
  die Packungen konstruiert und alle geordneten Kantenpaare mit der oberen
  Familie getrennt. Bei 75 dieser Paare wird keine Vollständigkeit des
  Hamiltonkreis-Universums durch Enumeration geprüft.
- Eine Negativkontrolle entfernt den zwingenden Ausnahme-Kreis X0011 und
  prüft, dass die von ihm allein erfüllte Anforderung dann unerfüllt bleibt.

Alle Prüfungen bestanden. Gesamtlaufzeit: ungefähr 6,9 Sekunden; Python 3.12.10.
Version, Plattform, deterministischer Algorithmus, Befehl, Laufzeiten und
Quelltext-Hashes stehen in `results.json`. Die größeren Konstruktionsprüfungen
und die endliche Enumeration ersetzen nicht das allgemeine Argument oben.

Wiederholung aus dem Projektverzeichnis:

```text
python artifacts/proof_audit_20260916/verify_formula.py
```
