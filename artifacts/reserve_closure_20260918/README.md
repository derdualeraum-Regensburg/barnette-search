# Schritt 4: Erhaltung der Quadrat-Reserve unter flächiger Quadrat-Einfügung

**Ergebnis:** Die in Schritt 3 eingeführte Quadrat-Robustheit bleibt unter
vollständiger Fortsetzung bei der betrachteten Quadrat-Einfügung erhalten.
Der folgende Beweis benutzt nur die lokale Pfadtabelle und die Struktur
der betroffenen Flächen; seine Aussage ist nicht auf den kleinen Census
beschränkt. Zusätzlich gibt es eine grobe quadratische Reservegrenze.
Das scharfe Kreisbudget für Conjecture 11.2 bleibt offen.

Dies ist ein intern geprüfter Beweisentwurf. Eine Neuheit oder Priorität
des Erhaltungssatzes wird nicht beansprucht.

## 1. Definitionen und Satz

Sei H ein Barnette-Graph mit festgelegter planarer Einbettung. Eine Familie
F von Hamiltonkreisen heißt hier **quadrat-robust**, wenn für jede
quadratische Fläche S, jedes Paar gegenüberliegender Seiten e,g von S und
jede Kante f außerhalb von E(S) ein Kreis C aus F existiert mit

    e,g in C und f nicht in C.

Zusätzlich verlangen wir gewöhnliche gerichtete Kanten-Trennung von F.
Beide Eigenschaften sind Eigenschaften der gewählten Kreisfamilie.

Sei Q die quadratische Fläche u,v,y,x, mit

    a=uv, b=xy, c=ux, d=vy.

Ersetze a durch u-p-q-v und b durch x-r-s-y und füge pr,qs ein.
Der neue Graph G hat vier zusätzliche Knoten. Mit L(F) bezeichnen wir
**alle** lokalen Fortsetzungen aller Kreise aus F, jeweils mit unveränderten
Kanten außerhalb von E(Q) und unveränderter Paarung der vier Anschlüsse.

**Erhaltungslemma.** Ist F trennend und quadrat-robust in H, so ist L(F)
trennend und quadrat-robust in G. Für

    t(F,Q) = Anzahl der C in F mit C geschnitten E(Q) = {c,d}

gilt genau

    |L(F)| = |F| + 2t(F,Q) <= 3|F|.

Die obere Größenabschätzung ist keine scharfe hsep-Schranke. Beliebiges
Weglassen von Fortsetzungen ist durch diesen Satz nicht gedeckt.

## 2. Die lokale Tabelle und erzwungene Zustände

Die vier Anschlusskanten außerhalb von Q heißen t_u,t_v,t_x,t_y.
Die Einschränkung eines Hamiltonkreises auf Q ist ein spannender
Pfadüberzug ohne geschlossene Komponente: Ein isolierter Vierkreis kann
wegen |V(H)|>=8 kein Hamiltonkreis sein. Bei zwei benutzten Anschlüssen
erhält man einen der vier Spannpfade; bei vier Anschlüssen einen der zwei
perfekten Matchings auf Q. Dies ergibt genau die sechs folgenden Zeilen.

| Alter Überzug | Benutzte Anschlüsse | Neue Überzüge |
|---|---|---|
| bcd | u,v | c,d,pq,pr,qs,sy,xr |
| ab | u,v,x,y | pq,qv,rs,sy,up,xr |
| cd | u,v,x,y | (1) d,pq,qs,rs,up,xr; (2) pr,qs,qv,sy,up,xr; (3) c,pq,pr,qv,rs,sy |
| abd | u,x | d,pq,qv,rs,sy,up,xr |
| abc | v,y | c,pq,qv,rs,sy,up,xr |
| acd | x,y | c,d,pr,qs,qv,rs,up |

Auch die neue Tabelle folgt durch Grad eins an benutzten Anschlüssen,
Grad zwei an allen übrigen Knoten und Ausschluss geschlossener Komponenten.
Jeder neue Überzug hat dieselbe Anschlusspaarung wie seine alte Zeile.
Deshalb bleibt das Zusammensetzen mit dem alten Außenanteil ein Hamiltonkreis.

Jede trennende alte Familie enthält mindestens einen Kreis jeder Zeile.
Die folgenden gewöhnlichen Trennanforderungen erzwingen sie jeweils eindeutig:

| Alter Überzug | Erzwingende Anforderung: enthalten, vermeiden |
|---|---|
| bcd | (b,a) |
| ab | (t_x,d) |
| cd | (t_x,a) |
| abd | (d,c) |
| abc | (c,d) |
| acd | (a,b) |

Damit kommen in L(F) alle acht neuen lokalen Überzüge vor. Die drei
Fortsetzungen der cd-Zeile erklären die Formel |F|+2t(F,Q); die
Fortsetzungen verschiedener alter Kreise sind verschieden, da Außenanteil
und Anschlusspaarung die alte lokale Zeile eindeutig bestimmen.

Die gewöhnliche Trennung von L(F) folgt aus dem Übertragungslemma von
Schritt 2: Es können genau die Anforderungen {pr,qs} × Z(F) fehlen,
wobei Z(F) die Außenkanten ohne alten Zeugen für c,d enthalten und f
vermeiden bezeichnet. Quadrat-Robustheit an Q gibt Z(F)=leer.

## 3. Welche quadratischen Flächen bleiben übrig?

Q wird durch die drei Zellen

    Q_L = u,p,r,x; Q_M = p,q,s,r; Q_R = q,v,y,s

ersetzt. Jede andere alte Fläche, die a oder b benutzt, wird entlang
dieser Seite um zwei Kanten länger. Alte Flächenlängen sind mindestens
vier und die Flächenränder sind wegen des 3-Zusammenhangs einfache Zyklen;
solche verlängerten Flächen sind anschließend keine Quadrate mehr. Alle übrigen
alten Flächen bleiben unverändert. Dies klassifiziert sämtliche neuen
quadratischen Flächen: drei neue Zellen und unveränderte alte Quadrate.
Die Einfügung wird in der Scheibe Q ausgeführt; außerhalb davon werden
keine weiteren Flächen aufgeteilt.

Ein unverändertes altes Quadrat S enthält weder a noch b und höchstens
eine der Seiten c,d. Enthielte es beide, wären dies gegenüberliegende
Seiten. Seine übrigen Seiten müssten entweder a,b sein oder die beiden
Diagonalen uy,vx. Die erste Möglichkeit wäre Q selbst; die zweite ist
wegen der Bipartition ausgeschlossen.

## 4. Reservezeugen für die drei neuen Zellen

Seien e,g gegenüberliegende Seiten einer neuen Zelle und f außerhalb
dieser Zelle.

**Fall A: f außerhalb des gesamten neuen Streifens.** Dann ist f eine alte
Kante außerhalb von Q. Für jedes der drei gegenüberliegenden Schienenpaare

    {up,xr}, {pq,rs}, {qv,sy}

liefert die alte Reserveanforderung a,b enthalten und f vermeiden einen
geeigneten Kreis: Jede Zeile mit a,b hat eine Fortsetzung mit dem
gewünschten Schienenpaar. Für die Sprossenpaare

    {c,pr}, {pr,qs}, {qs,d}

benutzt man entsprechend die alte Anforderung c,d enthalten und f
vermeiden. Die Tabelle enthält für jede einschlägige alte Zeile die
benötigte Fortsetzung. Die Außenkante f bleibt dabei vermieden.

**Fall B: f im Streifen, aber außerhalb der betreffenden Zelle.** Es gibt
genau 36 Anforderungen. Die folgende Tabelle nennt für jede einen neuen
lokalen Überzug; cd1,cd2,cd3 bezeichnen die drei Varianten der cd-Zeile.
Da jede alte Zeile in F vorkommt, ist jeder angegebene Überzug in L(F)
verfügbar. Die Tabelle ist eine vollständige explizite Zeugenliste.

| Enthaltenes Paar | Vermiedene Kante : Zeuge |
|---|---|
| up,xr | d:ab; pq:cd2; qs:ab; qv:cd1; rs:cd2; sy:cd1 |
| c,pr | d:cd3; pq:acd; qs:cd3; qv:bcd; rs:bcd; sy:acd |
| pq,rs | c:ab; d:ab; qv:cd1; sy:cd1; up:cd3; xr:cd3 |
| pr,qs | c:cd2; d:cd2; qv:bcd; sy:acd; up:bcd; xr:acd |
| qv,sy | c:ab; pq:cd2; pr:ab; rs:cd2; up:cd3; xr:cd3 |
| qs,d | c:cd1; pq:acd; pr:cd1; rs:bcd; up:bcd; xr:acd |

Damit sind sämtliche Reserveanforderungen der drei neuen Zellen erfüllt.

## 5. Reservezeugen für unveränderte Quadrate

Sei S ein unverändertes altes Quadrat mit gegenüberliegenden Seiten e,g.

**Hilfsbeobachtung.** Enthält ein alter Hamiltonkreis e,g, so enthält jede
seiner Fortsetzungen e,g. Liegen beide Seiten außerhalb von Q, ist dies
unmittelbar. Andernfalls enthält das Paar genau eine Seite aus {c,d},
etwa c=ux. Die andere Seite g liegt gegenüber von c in S. Die beiden
übrigen Seiten von S müssen t_u und t_x sein, da a,b nicht in S liegen
und H kubisch ist. Ein alter Kreis der cd-Zeile benutzt c,t_u,t_x.
Enthielte er auch g, enthielte er sämtliche vier Seiten von S. Diese
bildeten eine abgeschlossene Komponente, was für einen Hamiltonkreis
bei |V(H)|>=8 unmöglich ist. Ein Zeuge für e,g kann also nicht aus der
cd-Zeile stammen. In jeder anderen Zeile bleiben die Inzidenzen von c,d
bei der Fortsetzung unverändert. Der Fall mit d ist symmetrisch.

Sei nun f eine neue Kante außerhalb von E(S). Wir ziehen sie auf eine
alte außerhalb von E(S) liegende Kante f_0 zurück:

| Lage von f | Wahl von f_0 |
|---|---|
| f ist eine erhaltene alte Kante | f |
| f in {up,qv,rs} | a |
| f in {pq,xr,sy} | b |
| f in {pr,qs} | eine der Seiten c,d, die nicht in S liegt |

Die Wahl in der letzten Zeile ist möglich, weil S nicht beide Seiten c,d
enthält. Auch a,b liegen nicht in S. Die alte Quadrat-Robustheit liefert
also einen Kreis C mit e,g enthalten und f_0 vermieden.

Für erhaltene Außenkanten bleibt das Vermeiden unverändert. Ist f=c
oder f=d, garantiert die lokale Tabelle, dass eine alte Abwesenheit
dieser Seite bei jeder Fortsetzung erhalten bleibt. Für die sechs neuen
Schienenstücke zeigt die Tabelle jeweils mindestens eine Fortsetzung,
die f vermeidet, sobald f_0 fehlt. Fehlt eine von c,d, fehlen in der
zugehörigen neuen Zeile beide Sprossen pr,qs. In allen Fällen bleiben
gleichzeitig e,g enthalten, gemäß der Hilfsbeobachtung. Dies liefert den
gewünschten Reservezeugen in L(F).

Zusammen mit Abschnitt 4 beweist dies die Quadrat-Robustheit und damit
das Erhaltungslemma. ∎

## 6. Eine grobe, aber allgemeine Reserve-Kompression

Sei G ein Barnette-Graph auf n Knoten mit s quadratischen Flächen.
Sei F eine trennende, quadrat-robuste Familie und C eine beliebige
trennende Teilfamilie von F. Dann gibt es eine Reserve R innerhalb
von F ohne C mit

    C vereinigt R quadrat-robust,
    |R| <= 2s(n-1) <= (n+4)(n-1).

**Beweis.** Fixiere ein Quadrat und eines seiner zwei gegenüberliegenden
Seitenpaare. Wähle zunächst einen Kreis aus F, der dieses Paar enthält.
Er lässt genau n/2 Graphkanten aus und höchstens zwei davon im Quadrat.
Er vermeidet daher mindestens n/2-2 der 3n/2-4 Außenkanten. Es bleiben
höchstens n-2 Außenkanten ohne Zeugen. Wähle für jede einen weiteren
Zeugen aus F; Quadrat-Robustheit garantiert seine Existenz. Höchstens
n-1 Kreise genügen für dieses Seitenpaar. Über alle 2s Paare vereinigt
und um bereits in C enthaltene Kreise bereinigt ergibt dies R.
Euler liefert s<=n/2+2 und somit die zweite Abschätzung. ∎

Diese Schranke kontrolliert die Größe der gespeicherten Reserve unabhängig
von der Zahl früherer Einfügungen. Sie ist eine Obergrenze und wird nicht
als optimal behauptet. Sie setzt eine robuste verfügbare Familie voraus;
eine solche Familie für jeden beliebigen Barnette-Graphen folgt daraus nicht.

## 7. Konsequenz für das Induktionsprogramm

Unter der betrachteten Operation ist die qualitative Erhaltung der
Zusatzinformation damit bewiesen. Nach jedem Schritt kann eine vorhandene
trennende Teilfamilie um eine Reserve mit der obigen quadratischen Schranke
ergänzt werden. Insbesondere erbt eine beliebig lange Folge solcher
Einfügungen aus einer robusten Ausgangsfamilie wieder robuste Familien.

Für das scharfe Induktionsziel bleiben zwei wesentliche Aufgaben:

1. Innerhalb der verfügbaren Fortsetzungen eine Trennfamilie C' finden,
   deren Größe B(n+4) nicht überschreitet. Der Faktor drei und die grobe
   Reserve-Kompression liefern dieses Budget nicht. Benötigt wird weiterhin
   eine strukturelle Schranke für 2t+rho-delta.
2. Die benötigten Reduktionen für die gesamte Zielklasse rechtfertigen und
   für die Eindeutigkeitsaussage die Gleichheitsfälle charakterisieren.

Der Satz betrifft flächige Quadrat-Einfügungen der angegebenen Form.
Er wird nicht auf allgemeinere C4-Expansionen oder andere Operationen
übertragen, ohne deren Randzustände gesondert zu untersuchen.

## 8. Prüfung und Reproduktion

```console
python -I artifacts/reserve_closure_20260918/check.py
python -m pytest -q tests/test_reserve_closure.py
```

Der eigenständige Standardbibliothek-Prüfer enumeriert sämtliche lokalen
Kantenteilmengen, kontrolliert die sechs alten und acht neuen Überzüge,
die sechs erzwingenden Anforderungen, alle 36 inneren Reserveanforderungen
und die Zeugenregeln für Außenkanten und erhaltene Quadrate. Zusätzlich
wendet er **genau die Zeugenregeln dieses Beweises** auf die 206 früheren
Zertifikate an: 97.648 konkrete Implikationen werden geprüft. Er sucht
dabei keine frei gewählten Ersatzimplikationen.

Die globale Vollständigkeit und Graphvalidierung dieser Eingabezertifikate
ist Aufgabe des eigenständigen Prüfers aus Schritt 3. Die zusätzliche
Prüfung hier testet die expliziten Regeln des allgemeinen Beweises.
Der Beweis in den Abschnitten 1 bis 6 ist unabhängig von der Größe oder
Zusammensetzung dieses endlichen Testbestands.

`verification.json` dokumentiert Version, Kommando, Laufzeit und Quellhashes.
Die 214 gezielten Tests prüfen zusätzlich die konstruktive Reserve-Kompression
an allen 206 Übergängen und enthalten negative Kontrollen für falsche
Tabellen, Elternkreise und Zeugenregeln. Die vollständige Testsuite besteht
mit 1.045 Tests und zehn expliziten Auslassungen für externe Integrationen.
Die Prüfläufe und Quellhashes sind in `review.json` festgehalten.
Es werden weder ein Optimierungslöser noch Zufallsentscheidungen verwendet.
Der Prüflauf erneuert seine Laufzeitdatei; das Manifest beschreibt den
gespeicherten geprüften Stand. Bestehende Solver und Validierer bleiben
unverändert. Die Notiz ist noch nicht in das Hauptmanuskript integriert.
