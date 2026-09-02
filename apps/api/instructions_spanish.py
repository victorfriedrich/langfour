INSTRUCTION_VERBS = """Generate all conjugations / tiempos simples for the verb {word} as json dictionary. Also list the one past perfect form
Answer structure:
{{ 
"presente": [],
"imperfecto": []
"indefinido": []
"futuro": []
"condicional": []

"perfecto root": string
"gerundio": string
}}
"""

INSTRUCTION_VERB_COMPLETE = """Generate the gerundio for the verb {word} as json entry.
Answer structure:
{{ 
"gerundio": result
}}
"""

INSTRUCTION_NOUNS = """Generate a short unnested json array of all singular and plural forms of the noun {word} without article. 

Examples:
- [\"carta\", \"cartas\"]
- [\"centro\", \"centros\"]
- [\"padre\", \"padres\"]
"""
INSTRUCTION_ADJECTIVE = """Generate a short json array of masculine, feminine, singular, and plural forms for the adjective {word}. 

Examples:
[\"inglés\", \"ingleses\", \"inglesa\", \"inglesas\"]
"""

INSTRUCTION_GROUP = """Parse the following large text into small string json groups [g1, g2, ..., gn] as follows:
- Verbs form a group with pronouns and parts related to their tense ("se palpaba", "se cancela", "ha anunciado")
- Nouns form a group with the associated article ("el concierto", "la fila", "la hora")
- Otherwise groups are usually one word long
- Very rarely, groups that form a colloquial expression can form a group ("a través de", "cada uno"). This should be avoided unless it really makes sense
- Characters like new lines, dots, commas, quotation marks, nquestion marks, exclamation marks and numbers also form their own group

Examples: 
"Lo ha hecho a través de una carta publicada a través de sus redes sociales" is parsed to ["Lo", "ha hecho", "a través de", "una carta", "publicada", "a través de", "sus", "redes", "sociales"]

"La decisión llega después de que sus compañeros demócratas perdieran la" is parsed to ["La decisión", "llega", "después de que", "sus", "compañeros", "demócratas", "perdieran", "la"]

"No está donde debe estar. Para estas alturas del verano, debería ubicarse encima del archipiélago y, sin embargo, se encuentra desplazado hacia el sur.\n«Si se va hacia el sur, como es el caso." is parsed to ["No", "está", "donde", "debe", "estar", ". ", "Para", "estas", "alturas", "del", "verano", debería", "ubicarse", "encima", "del, "archipiélago", "y", ", ", "sin", "embargo", ", ", "se encuentra", "desplazado", "hacia", "el", "sur", ".\n«", "Si", "se va hacia", "el sur", ", ", "como", "es", "el", "caso", "."]

Text to parse:
"""

INSTRUCTION_SUMMARIZE = """Summarize the following text in 2-3 words that can be used as a filename. The summary should be concise and descriptive.

Text to summarize:
{text}

Summary:"""

INSTRUCTION_FILTER_LANGUAGE = """From a spanish text, filter out words that are not suitable to be added to learning flashcards. For this, analyze the following text and identify words that are either:
    1. Person names
    2. Company names or websites
    3. Sections of english text (e.g. "what the fuck", "get by") that are not spanish
    4. Unique location names (e.g. Clarion Hotel, Queens, NY, Clarque Quay)
    5. Unique product names (e.g. iPhone, MacBook Pro, Samsung S22, YouTuber)
    6. Political descriptions (e.g. Convención Nacional Demócrata, Partido Popular, etc)
    7. Unique event names (e.g. Copa América, Festival de Cannes, etc)
    8. Unique sports names (e.g. Real Madrid, FC Barcelona, etc)
    9. Unique references to culture, history, geography, science, mathematics, music, and art (e.g. Star Wars, World War II, Amazon Rainforest)
    10. Unique english expressions (e.g. "break the ice", "self-confident", "the newsletter")

    Return **ONLY** a single-level JSON array containng just words to be filtered from the text.

    Text to analyze: "{text}"
    """
    
INSTRUCTION_ROOT_FORM = """For the word '{word}' return a 2 element json dictionary that determines the "type" which is either "verb" if it could be a verb, "noun", "adjective", or otherwise "other".
    
    Also include a "key":
    - For verbs of any conjugation it is the root form. 
    - For nouns it is the singular (!) full verb including spanish article
    - For adjectives also give the singular (!) male root form
    - If it's neither (other) the key is the word itself
    """
    
INSTRUCTION_VERIFY_NEW_WORD = """You are a meticulous Spanish lexicographer reviewing one candidate dictionary entry before it is saved. Another process already picked the root and generated its forms -- your job is only to review that output, not redo it.

root: "{root}" (type: {type})
forms: {forms}

Default to trusting this entry. Only set "definitely_not_valid" to true if you are CONFIDENT something below is actually wrong -- not merely unsure or if the word is simply rare, regional, or archaic:
1. "root" is not a real, correctly-spelled Spanish word -- e.g. it's a proper name, brand, a foreign-language word (Italian/French/Portuguese/Latin/English etc.), a misspelling, or a conjugated/inflected surface form rather than the canonical dictionary form.
2. One or more of "forms" is not actually a Spanish inflection of THIS root -- e.g. it's a form of a different, unrelated word, a foreign-language word, an English gloss, or nonsense.

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

INSTRUCTION_VERIFY_LANGUAGE = """From the following words, identify those that are not valid spanish words. This includes mainly words that are not spanish, but also misspellings and:
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