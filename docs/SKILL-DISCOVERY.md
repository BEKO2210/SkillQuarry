# Finding the next skill

A prompt for a research model, and the reasoning behind it.

Two skills taught us what to ask for. **CrypticShift** had a strong idea and
died at its own final gate: the advantage it produced was smaller than the cost
of verifying the candidates it produced. **LockScope** survived because it had a
truth outside itself — `rustc` decided whether a future was `Send`, not the tool
and not a human's taste.

So the search is not "what would be a nice tool". It is: **where does a machine
perceive something a human structurally cannot, and can that perception be
checked by something that is not the machine?**

Four properties every candidate must have:

1. **Machine-native perception.** The signal lives in artifacts humans do not
   read (lock files, build graphs, CI logs across months, resolution orders,
   coverage traces, compiler IR, LSP indices, binary diffs) or only appears
   across a scale no person holds in their head (500 repositories, 3 years of
   history, every path through a dependency graph).
2. **Cheap verification, expensive discovery.** Finding is hard, checking is
   cheap. If verifying a candidate costs as much as producing it, the tool
   collapses — that is exactly how CrypticShift died.
3. **An external oracle.** Something that is not this tool and not an opinion
   can say "right" or "wrong": a compiler, a runtime, a proof, a historical
   commit where a human fixed the exact thing, a reproducible failure.
4. **Falsifiable in advance.** The kill criterion is written before the work
   starts, and it is one a plausible-sounding idea can actually fail.

The prompt below is the paste-ready version. It asks for candidates first,
falsification second, and implementation only after both.

---

## The prompt

````text
Du bist Forschungs-Ingenieur fuer agentische Werkzeuge. Ich betreibe SkillQuarry,
einen Marktplatz fuer Skills, die KI-Coding-Agenten benutzen:
https://github.com/BEKO2210/SkillQuarry — vier Skills, jeder mit eingefrorenem
Testprotokoll, echten Repository-Belegen und CI auf Ubuntu und macOS.

AUFTRAG
Finde Skill-Kandidaten, die ein MENSCH NICHT FINDEN WUERDE — nicht weil sie
kompliziert sind, sondern weil das Signal ausserhalb menschlicher Wahrnehmung
liegt. Recherchiere aktiv im Internet und belege jede Behauptung mit Quelle:
echte Repositories, echte Commits, echte Issue-Nummern, echte Messungen.
Keine Blogpost-Weisheiten, keine Erfindungen.

WO DU SUCHST (nicht abschliessend, aber die Richtung)
- Artefakte, die niemand liest: Lockfiles, Aufloesungs-Reihenfolgen, Build-
  Graphen, CI-Logs ueber Monate, Coverage-Traces, Compiler-Zwischencode,
  Sprachserver-Indizes, Binary-Diffs, Cache-Schluessel, Testlauf-Historien.
- Signale, die erst bei einer Menge sichtbar werden, die kein Kopf haelt:
  hunderte Repositories, Jahre Historie, jeder Pfad durch einen Graphen.
- Fehler, die systematisch unsichtbar sind: stiller Erfolg, uebernommene
  Defaults, ABWESENHEIT von etwas (der Test, der nie lief; der Zweig, der nie
  genommen wurde; die Freigabe, die nie geprueft wurde).
- Wahrheiten, die zwischen zwei Werkzeugen verloren gehen und die keines
  allein sehen kann.

VIER PFLICHTEIGENSCHAFTEN — fehlt eine, ist der Kandidat raus
1. MASCHINENWAHRNEHMUNG: Das Signal liegt in Artefakten oder Mengen, die ein
   Mensch praktisch nicht ueberblickt. Begruende, warum ein erfahrener
   Entwickler es NICHT bemerkt.
2. ASYMMETRIE: Finden teuer, Pruefen billig. Nenne beides in Groessenordnungen.
   Wenn Pruefen so teuer ist wie Finden, verwirf den Kandidaten selbst.
3. EXTERNES ORAKEL: Etwas ausserhalb des Werkzeugs entscheidet richtig/falsch —
   ein Compiler, eine Laufzeit, ein Beweis, ein historischer Commit, in dem ein
   Mensch genau das repariert hat, oder ein reproduzierbarer Fehlschlag.
   Ein Sprachmodell als Richter ist KEIN Orakel.
4. FALSIFIZIERBARKEIT: Formuliere VORHER das Kriterium, an dem der Kandidat
   stirbt.

VERBOTEN
- Wrapper um vorhandene Linter, Formatter oder Scanner.
- Alles, dessen Ergebnis ein Mensch beurteilen muss ("verbessert Lesbarkeit").
- "KI-gestuetztes X" ohne mechanischen Kern.
- Ideen ohne echtes Repository, an dem man sie heute pruefen kann.
- Biologische oder kosmische Metaphern als Ersatz fuer einen Mechanismus.

LIEFERUNG — TEIL 1: SIEBEN KANDIDATEN
Je Kandidat hoechstens 200 Woerter, in genau dieser Form:

  NAME
  BEOBACHTUNG   Welches Signal? In welchem Artefakt? Warum sieht ein Mensch es nicht?
  MECHANISMUS   Wie wird es mechanisch gefunden? Konkrete Werkzeuge, kein Zauber.
  ORAKEL        Wer sagt unabhaengig, ob ein Fund echt ist?
  ASYMMETRIE    Kosten Finden vs. Pruefen, mit Zahlen.
  BELEG         2-3 echte Repositories mit Commit-SHA, wo das Problem existiert
                oder ein Mensch es nachweislich repariert hat.
  TODESKRITERIUM Woran scheitert der Kandidat?
  WARUM NEU     Was existiert heute schon, und warum reicht es nicht?

Sortiere danach, wie WEIT die Idee von menschlicher Wahrnehmung entfernt ist —
nicht danach, wie nuetzlich sie klingt. Mindestens drei Kandidaten muessen
Artefakte betreffen, die nicht der Quelltext sind.

LIEFERUNG — TEIL 2: BILLIGE VORPRUEFUNG
Waehle die drei staerksten Kandidaten. Fuer jeden: ein Experiment unter zwei
Stunden, das zeigt, ob das Signal ueberhaupt existiert — an einem echten,
gepinnten Repository, mit erwartetem Ergebnis, das FALSCH sein kann. Nenne die
Befehle. Nenne, was du siehst, wenn die Idee falsch ist.

LIEFERUNG — TEIL 3: EIN EINGEFRORENES PROTOKOLL
Nur fuer den Gewinner. Vor jeder Implementierung festschreiben:
- Bestehensgrenzen als Zahlen (nicht "funktioniert gut");
- gepinnte Repositories mit Commit-SHA, davon mindestens eines als
  historisches Orakel (Mensch hat es dort repariert);
- Laufzeit-Budget in Sekunden;
- Baseline, gegen die verglichen wird (auch: was war vorher schon rot);
- was NICHT behauptet wird.

REGELN FUER DEINE ANTWORT
- Englisch fuer alles, was spaeter ins Repo geht (SKILL.md, Code, Berichte).
- Kein Marketing. Kein "revolutionaer". Zahlen statt Adjektive.
- Wenn du etwas nicht belegen kannst, schreib "unbelegt" dahinter.
- Wenn dir auffaellt, dass ein eigener Kandidat eine der vier Pflicht-
  eigenschaften verletzt: sag es und verwirf ihn selbst. Ein ehrlich
  verworfener Kandidat ist mehr wert als sieben, die gut klingen.
````

---

## What happens with the answer

The candidates come back to this repository for review. A candidate is only
worth implementing when its cheap probe actually produced the signal, and only
worth publishing when the frozen protocol passed on Ubuntu **and** macOS with
real repositories — the same bar Strata, Cordon, RanGate and LockScope cleared.

A skill that fails its own final gate does not enter the repository. That has
happened once, and the removal was total.
