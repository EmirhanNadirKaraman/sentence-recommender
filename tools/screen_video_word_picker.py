"""Conservative screening of an existing private snapshot; never changes knowledge.

Use pdftotext -bbox-layout on Goethe's A1 SD1 and A2 word-list PDFs first.
Only alphabetical headword columns are read, never example sentences.
The PDFs/complete lists are not distributed in the project.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    'A1': 'https://www.goethe.de/pro/relaunch/prf/de/A1_SD1_Wortliste_02.pdf',
    'A2': 'https://www.goethe.de/pro/relaunch/prf/mk/Goethe-Zertifikat_A2_Wortliste.pdf',
}
# Explicit semantic pairs, not edit-distance guesses. Intentionally omit
# Bank, Gift, Rat, Chef, aktuell, eventuell, bekommen, sensibel, Gymnasium.
# Recognizable English cognates can still have additional German meanings.
PAIRS = '''Aspekt|aspect
Funktion|function
Doktor|doctor
Student|student
Prozess|process
Modell|model
Kontakt|contact
Kilometer|kilometer
Dollar|dollar
Theater|theater
Computer|computer
Patient|patient
Professor|professor
Institut|institute
Risiko|risk
Organisation|organisation / organization
Diskussion|discussion
Methode|method
Konzept|concept
Literatur|literature
November|November
Position|position
Theorie|theory
Material|material
Produktion|production
Hotel|hotel
Analyse|analysis
Partner|partner
Faktor|factor
Objekt|object
Direktor|director
Union|union
Geographie|geography
Qualität|quality
Winter|winter
Generation|generation
Zentimeter|centimeter
Instrument|instrument
Semester|semester
Tradition|tradition
Interview|interview
Basis|basis
Element|element
Terror|terror
Definition|definition
Nation|nation
Hobby|hobby
Phase|phase
Kandidat|candidate
Industrie|industry
Institution|institution
Trainer|trainer
Club|club
Terrorismus|terrorism
Effekt|effect
Medizin|medicine
Software|software
Bus|bus
Kommission|commission
Terrorist|terrorist
Temperatur|temperature
Alternative|alternative
Manager|manager
Religion|religion
Koalition|coalition
Tourist|tourist
Test|test
Realität|reality
Parlament|parliament
Formel|formula
Debatte|debate
Kilogramm|kilogram
Mathematik|mathematics
Minister|minister
Management|management
Millimeter|millimeter
Tourismus|tourism
Investition|investment
Therapie|therapy
Atmosphäre|atmosphere
PC|PC
Strategie|strategy
Park|park
Kombination|combination
Fotografie|photography
Radio|radio
Detail|detail
Organismus|organism
Kategorie|category
Integration|integration
Dimension|dimension
Journalist|journalist
Star|star
Standard|standard
CD|CD
Initiative|initiative
Experiment|experiment
Komponente|component
Seminar|seminar
Technologie|technology
Kamera|camera
plus|plus
TV|TV
Identität|identity
Service|service
Reform|reform
Charakter|character
Norm|norm
Restaurant|restaurant
Argument|argument
Existenz|existence
Disziplin|discipline
Opposition|opposition
Motiv|motif
Training|training
Station|station
Café|cafe
Trend|trend
Operation|operation
Qualifikation|qualification
Variante|variant
Kapital|capital
Motor|motor
Republik|republic
Kooperation|cooperation
Symbol|symbol
Fan|fan
Tour|tour
Architekt|architect
Business|business
Marketing|marketing
Kindergarten|kindergarten
Infektion|infection
Kontinent|continent
Elektron|electron
Transport|transport
Revolution|revolution
Distanz|distance
Alkohol|alcohol
Horizont|horizon
Konferenz|conference
Organ|organ
Ring|ring
Center|center
Protein|protein
Gold|gold
Interpretation|interpretation
Dialog|dialogue
Gas|gas
Pilot|pilot
Resultat|result
Baby|baby
Differenz|difference
City|city
Protest|protest
Medium|medium
Taxi|taxi
Statistik|statistics
Defizit|deficit
Format|format
Motto|motto
Premiere|premiere
Tennis|tennis
Sektor|sector
Symptom|symptom
Virus|virus
Dialekt|dialect
Infrastruktur|infrastructure
Mission|mission
Katalog|catalogue / catalog
Skandal|scandal
Show|show
Reflexion|reflection
Gramm|gram
Kontext|context
Zone|zone
Akademie|academy
Dokument|document
Fusion|fusion
Status|status
Regime|regime
Solidarität|solidarity
Stabilität|stability
Investor|investor
Diagnose|diagnosis
Front|front
Orientierung|orientation
Senat|senate
Ensemble|ensemble
Festival|festival
Liter|liter
Jazz|jazz
Architektur|architecture
Atom|atom
Biologie|biology
Butter|butter
Champion|champion
Konstruktion|construction
Party|party
Milligramm|milligram
Planet|planet
Salon|salon
Talent|talent
Spektrum|spectrum
Villa|villa
Rezession|recession
Design|design
Chaos|chaos
Chip|chip
General|general
Hypothese|hypothesis
Islam|Islam
Magazin|magazine
Mythos|myth
Kassette|cassette
Spezialist|specialist
Ticket|ticket
Periode|period
Tunnel|tunnel
Uniform|uniform
Block|block
Bar|bar
Forum|forum
Motivation|motivation
Option|option
Respekt|respect
Rose|rose
Diplom|diploma
Relation|relation
Profil|profile
Volumen|volume
Vitamin|vitamin
modern|modern
privat|private
absolut|absolute
national|national
komplex|complex
intensiv|intensive
ideal|ideal
global|global
exakt|exact
maximal|maximal
parallel|parallel
optimal|optimal
digital|digital
real|real
objektiv|objective
radikal|radical
stabil|stable
attraktiv|attractive
abstrakt|abstract
indirekt|indirect
relevant|relevant
subjektiv|subjective
analog|analog
quasi|quasi
blind|blind
intellektuell|intellectual
effektiv|effective
nervös|nervous
konstant|constant
logisch|logical
liberal|liberal
spontan|spontaneous
organisch|organic
extra|extra
flexibel|flexible
formal|formal
kreativ|creative
elegant|elegant
professionell|professional
linear|linear
extern|external
emotional|emotional
effizient|efficient
intelligent|intelligent
mobil|mobile
blond|blond
explizit|explicit
permanent|permanent
illegal|illegal
mild|mild
minimal|minimal
strikt|strict
bitter|bitter
absurd|absurd
radioaktiv|radioactive'''
ENGLISH = dict(line.split('|', 1) for line in PAIRS.splitlines())


def plain(key):
    """Only plain words and article+noun; valency/idioms stay manual."""
    key = re.sub(r'^(?:der|die|das)\s+', '', key.strip())
    return key if re.fullmatch(r'[\wÄÖÜäöüßé]+', key) else None


def goethe_entries(path, level):
    ns = {'h': 'http://www.w3.org/1999/xhtml'}
    pages = ET.parse(path).findall('.//h:page', ns)
    result = {}
    start, stop = (9, 27) if level == 'A1' else (8, 31)
    for number in range(start, stop + 1):
        page = pages[number - 1]
        columns = [(140, 214, 230)] if level == 'A1' else [(34, 40, 105), (303, 310, 374)]
        for low, high, edge in columns:
            lines = []
            for line in page.findall('.//h:line', ns):
                if low <= float(line.get('xMin')) <= high and 110 < float(line.get('yMin')) < 780:
                    # Some lines fuse headword and example: crop each word.
                    words = [w.text or '' for w in line if float(w.get('xMax')) <= edge]
                    if words:
                        lines.append((float(line.get('yMin')), ' '.join(words)))
            lines.sort()
            for i, (_, text) in enumerate(lines):
                if text.endswith('-') and i + 1 < len(lines) and lines[i + 1][0] - lines[i][0] < 14:
                    text = text[:-1] + lines[i + 1][1]
                text = text.split(',')[0].split('(')[0].strip()
                # Never match conjugation rows or isolated single-letter headings.
                if text.startswith(('hat ', 'ist ')) or len(text) < 2:
                    continue
                key = plain(text)
                if key:
                    result.setdefault(key, {'level': level, 'entry': text, 'page': number,
                                                       'source': SOURCES[level]})
    # Explicit items from the separate word-group pages, not inferred from
    # example sentences. Preserve case: adjective mittel != noun Mittel.
    groups = {
        6: 'eins zwei drei vier fünf sechs sieben acht neun zehn elf zwölf dreizehn vierzehn fünfzehn sechzehn siebzehn achtzehn neunzehn zwanzig einundzwanzig dreißig vierzig fünfzig sechzig siebzig achtzig neunzig hundert tausend Million Milliarde',
        7: 'Sekunde Minute Stunde Tag Woche Jahr Wochentag Wochenende Sonntag Montag Dienstag Mittwoch Donnerstag Freitag Samstag Sonnabend Morgen Vormittag Mittag Nachmittag Abend Nacht Januar Februar März April Mai Juni Juli August September Oktober November Dezember',
        8: 'Frühling Frühjahr Sommer Herbst Winter Euro Cent Meter Zentimeter Kilometer Quadratmeter Grad Prozent Liter Gramm Pfund Kilo Kilogramm Deutschland Europa Deutsche Deutscher Europäer deutsch europäisch türkisch finnisch mexikanisch schwarz grau blau grün weiß rot gelb braun Norden Süden Westen Osten',
    } if level == 'A1' else {
        6: 'Englisch Französisch Biologie Chemie Geografie Mathematik Physik Religion Karneval Ostern Weihnachten Neujahr Silvester Mitternacht täglich tagsüber morgens vormittags mittags nachmittags abends nachts',
        7: 'einmal zweimal dreimal viermal erstens zweitens drittens viertens',
    }
    for page, words in groups.items():
        for word in words.split():
            result.setdefault(word, {'level': level, 'entry': word, 'page': page,
                                    'source': SOURCES[level]})
    return result


def screen(snapshot, levels):
    counts = Counter()
    for card in snapshot['cards']:
        member_reasons = []
        for member in card['members']:
            key = plain(member['key'])
            evidence = []
            if key and key in levels:
                entry = levels[key]
                evidence.append({'code': 'basic-level', **entry,
                                 'text': f"Goethe {entry['level']} kelime listesinde: {entry['entry']} (s. {entry['page']})."})
            # Preserve noun/adjective case distinctions (e.g. arm vs Arm).
            english = ENGLISH.get(key) if key else None
            if english:
                evidence.append({'code': 'english-cognate', 'english': english,
                                 'text': f'İngilizceye açıkça benziyor: {key} → {english}. Temel anlam için ayrı video önceliği düşük.'})
            member_reasons.append({'key': member['key'], 'evidence': evidence})
        card.pop('auto_no', None)
        # A family decision affects ALL unknown usages. One unverified idiom
        # or advanced construction keeps the whole card for manual review.
        if member_reasons and all(m['evidence'] for m in member_reasons):
            reasons = list(dict.fromkeys(e['text'] for m in member_reasons for e in m['evidence']))
            card['auto_no'] = {'text': ' '.join(reasons), 'members': member_reasons}
            counts['auto_no'] += 1
            counts['units'] += len(card['members'])
            for code in {e['code'] for m in member_reasons for e in m['evidence']}:
                counts[code] += 1
    snapshot['screening'] = {'version': 1, 'policy': 'explicit-cognates-and-goethe-a1-a2',
                             'sources': SOURCES, 'counts': dict(counts),
                             'manual_cards': len(snapshot['cards']) - counts['auto_no']}
    return snapshot


def write(snapshot, path):
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    payload = json.dumps(snapshot, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    template = (ROOT / 'tools/video_word_picker.html').read_text(encoding='utf-8')
    html = path.with_name(path.name.replace('-snapshot.json', '.html'))
    html.write_text(template.replace('__SNAPSHOT__', payload), encoding='utf-8')
    no_cards = [c for c in snapshot['cards'] if c.get('auto_no')]
    report = {'policy': snapshot['screening'], 'cards': no_cards}
    path.with_name(path.name.replace('-snapshot.json', '-automatic-no.json')).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    path.with_name(path.name.replace('-snapshot.json', '-automatic-no.tsv')).write_text(
        'Kelime\tSebep\n' + ''.join(f"{c['word']}\t{c['auto_no']['text']}\n" for c in no_cards), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, default=ROOT / 'docs/video-selection/emir-video-words-snapshot.json')
    parser.add_argument('--a1-bbox', type=Path, required=True)
    parser.add_argument('--a2-bbox', type=Path, required=True)
    args = parser.parse_args()
    levels = {**goethe_entries(args.a2_bbox, 'A2'), **goethe_entries(args.a1_bbox, 'A1')}
    snapshot = screen(json.loads(args.snapshot.read_text(encoding='utf-8')), levels)
    write(snapshot, args.snapshot)
    print(json.dumps(snapshot['screening'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
