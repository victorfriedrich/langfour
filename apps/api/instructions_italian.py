INSTRUCTION_VERBS = """Generate all conjugations / tempi semplici for the verb {word} as json dictionary. Don't include auxiliary and modal verbs!
Answer structure:
{{ 
"presente": [],
"imperfetto": [],
"passato remoto": [],
"futuro semplice": [],
"condizionale": [],
"congiuntivo presente": [],
"congiuntivo passato": [],
"congiuntivo imperfetto": [],
"congiuntivo trapassato": [],

"radice perfetta": string,
"gerundio": string
}}
"""

INSTRUCTION_VERB_COMPLETE = """Generate the gerundio for the verb {word} as json entry.
Answer structure:
{{ 
"gerundio": result
}}
"""

INSTRUCTION_NOUNS = """Generate a short unnested json array of all singular and plural forms of the italian noun {word} without article. Don't translate to english.

Examples:
- [\"carta\", \"carte\"]
- [\"centro\", \"centri\"]
- [\"padre\", \"padri\"]
"""

INSTRUCTION_ADJECTIVE = """Generate a JSON array of Italian adjective forms for "{word}". Include masculine singular, masculine plural, feminine singular, and feminine plural forms. If the adjective is invariable or has fewer forms, include only the applicable forms. Don't translate to English.
Examples:

- ["italiano", "italiani", "italiana", "italiane"]
- ["verde", "verdi"]
- ["blu"]
- ["grande", "grandi"]
- ["veloce", "veloci"]

"""

INSTRUCTION_GROUP = """Parse the following large text into small string json groups [g1, g2, ..., gn] as follows:
- Verbs form a group with pronouns and parts related to their tense ("si percepiva", "si cancella", "ha annunciato")
- Nouns form a group with the associated article ("il concerto", "la fila", "l'ora")
- Otherwise groups are usually one word long
- Very rarely, groups that form a colloquial expression can form a group ("attraverso", "ciascuno"). This should be avoided unless it really makes sense
- Characters like new lines, dots, commas, quotation marks, question marks, exclamation marks and numbers also form their own group

Examples: 
"Lo ha fatto attraverso una lettera pubblicata attraverso i suoi social media" is parsed to ["Lo", "ha fatto", "attraverso", "una lettera", "pubblicata", "attraverso", "i", "suoi", "social", "media"]

"La decisione arriva dopo che i suoi compagni democratici hanno perso la" is parsed to ["La decisione", "arriva", "dopo che", "i", "suoi", "compagni", "democratici", "hanno", "perso", "la"]

"Non è dove dovrebbe essere. Per questo periodo dell'estate, dovrebbe trovarsi sopra l'arcipelago e, tuttavia, si trova spostato verso sud.\n«Se va verso sud, come è il caso." is parsed to ["Non", "è", "dove", "dovrebbe", "essere", ". ", "Per", "questo", "periodo", "dell'", "estate", "dovrebbe", "trovarsi", "sopra", "l'", "arcipelago", "e", ", ", "tuttavia", ", ", "si trova", "spostato", "verso", "sud", ".\n«", "Se", "va verso", "sud", ", ", "come", "è", "il", "caso", "."]
"""

INSTRUCTION_SUMMARIZE = """Summarize the following text in 2-3 words that can be used as a filename. The summary should be concise and descriptive.

Text to summarize:
{text}

Summary:"""

INSTRUCTION_FILTER_LANGUAGE = """From an italian text, filter out words that are not suitable to be added to learning flashcards. For this, analyze the following text and identify words that are either:
    1. Person names
    2. Company names or websites
    3. Sections of english text (e.g. "what the fuck", "get by") that are not italian
    4. Unique location names (e.g. Hotel Clarion, Roma, Italia, Ponte Vecchio)
    5. Unique product names (e.g. iPhone, MacBook Pro, Samsung S22, YouTuber)
    6. Political descriptions (e.g. Partito Democratico, Movimento 5 Stelle, etc)
    7. Unique event names (e.g. Festival di Sanremo, Biennale di Venezia, etc)
    8. Unique sports names (e.g. Juventus, AC Milan, etc)
    9. Unique references to culture, history, geography, science, mathematics, music, and art (e.g. La Divina Commedia, Seconda Guerra Mondiale, Foresta Amazzonica)
    10. Unique english expressions (e.g. "break the ice", "self-confident", "the newsletter")

    Return a single-level JSON array containing just words to be filtered from the text.

    Text to analyze: "{text}"
    """
    
INSTRUCTION_CATEGORIZE = """Given a title and the first words of a non-english video, characterize it and provide english subcategories and tags to label it.
    Return a single-level JSON array containing just 4-5 subcategories / tags that describe what type of video it is
    
    title: {title}
    text:
    {text}
    """
    
INSTRUCTION_ROOT_FORM = """For the italian word '{word}' return a 2 element json dictionary that determines the "type" which is either "verb" if it could be a verb, "noun", "adjective", or otherwise "other".
    In words ending with *, the star represents multiple letters being allowed there
    
    Also include a "key":
    - For verbs of any conjugation it is the root form. 
    - For nouns it is the singular (!) full noun including italian article. If it's not a noun, return the word itself
    - For adjectives also give the singular (!) male root form. If it's not an adjective, return the word itself
    - If it's neither (other) the key is the word itself (this is the case for e.g. "ciao", "fatta", "nelle", "dall'")
    """
    
INSTRUCTION_VERIFY_NEW_WORD = """You are a meticulous Italian lexicographer reviewing one candidate dictionary entry before it is saved. Another process already picked the root and generated its forms -- your job is only to review that output, not redo it.

root: "{root}" (type: {type})
forms: {forms}

Default to trusting this entry. Only set "definitely_not_valid" to true if you are CONFIDENT something below is actually wrong -- not merely unsure or if the word is simply rare, regional, or archaic:
1. "root" is not a real, correctly-spelled Italian word -- e.g. it's a proper name, brand, a foreign-language word, a misspelling, or a conjugated/inflected surface form rather than the canonical dictionary form.
2. One or more of "forms" is not actually an Italian inflection of THIS root -- e.g. it's a form of a different, unrelated word, a foreign-language word, an English gloss, or nonsense.

Return a JSON object:
{{
  "definitely_not_valid": boolean,
  "reason": string,
  "translation": string
}}

"reason": if definitely_not_valid is true, say specifically what's wrong; otherwise a brief confirmation.
"translation": a 1-3 word English translation of "root", without a leading article for nouns. Empty string if definitely_not_valid is true.

Return ONLY the JSON object.
"""

INSTRUCTION_VERIFY_LANGUAGE = """From the following words, identify those that are not suitable to be added to learning flashcards. This includes mainly words that are not spanish, but also misspellings and:
    1. Person names
    2. Company names or website domains
    3. English words that are not spanish
    4. Unique location names (e.g. Clarion, Hotel, Queens, NY, Clarque, Quay)
    5. Unique product names (e.g. iPhone, MacBook, Pro, Samsung, S22, YouTuber)
    6. Unique sport related words (e.g. BVB, FCB)

Return only the words that are problematic in an unnested JSON array: ["word1", "word2", ...] 
Terms to check:

{word_list}
"""