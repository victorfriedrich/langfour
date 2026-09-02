INSTRUCTION_VERBS = """Generate all conjugations for the german verb {word} as json dictionary. Also list the one past perfect form
Don't include the personal pronouns, and don't include the modal verbs. 
Don't include auxiliary verbs! Keine Modalverben!
So provide the forms of the verb and don't include anything like "habe", "hatte", "hatten", "bist", "werde", "würde", "wirst" etc. NO AUXILIARY VERBS; NO MODAL VERBS!!

Answer structure:
{{ 
"Präsens": [],
"Präteritum": [],
"Perfekt": [],
"Futur I": [],
"Futur II": [],  // Added future perfect tense
"Plusquamperfekt": [],  // Added past perfect tense
"Konjunktiv II": [],
"Konjunktiv I": [],

"Partizip II": string,
"Infinitiv": string
}}
"""

INSTRUCTION_VERB_COMPLETE = """Generate the Partizip II for the verb {word} as a JSON entry.
Answer structure:
{{ 
"Partizip II": result
}}
"""

INSTRUCTION_NOUNS = """Generate a short unnested JSON array of all singular and plural forms of the german noun {word} without article. 
If it doesn't have a plural, e.g. because it is a proper noun, omit the plural.

Examples:
- [\"Buch\", \"Bücher\"]
- [\"Haus\", \"Häuser\"]
- [\"Vater\", \"Väter\"]
- [\"Hund\", \"Hunde\"]
"""

INSTRUCTION_ADJECTIVE = """Generate a short unnested JSON array of singular and plural forms for the german adjective {word}. Consider different cases.
Just return a list of words usable by python.

Examples:
[\"deutsch\", \"deutsche\", \"deutscher\", \"deutschen\"]
"""

INSTRUCTION_GROUP = """Parse the following large text into small string JSON groups [g1, g2, ..., gn] as follows:
- Verbs form a group with pronouns and parts related to their tense ("er hat", "sie wird", "wir sind gegangen")
- Nouns form a group with the associated article ("das Konzert", "die Reihe", "der Moment")
- Otherwise groups are usually one word long
- Very rarely, groups that form a colloquial expression can form a group ("durch", "jeder"). This should be avoided unless it really makes sense
- Characters like new lines, dots, commas, quotation marks, question marks, exclamation marks and numbers also form their own group

Examples: 
"Er hat es durch einen Brief veröffentlicht, der durch seine sozialen Medien ging" is parsed to ["Er", "hat", "es", "durch", "einen Brief", "veröffentlicht", "der", "durch", "seine", "sozialen", "Medien", "ging"]

"Die Entscheidung kommt, nachdem seine demokratischen Kollegen verloren haben" is parsed to ["Die Entscheidung", "kommt", "nachdem", "seine", "demokratischen", "Kollegen", "verloren", "haben"]

"Es ist nicht dort, wo es sein sollte. Für diese Jahreszeit sollte es über dem Archipel sein und dennoch ist es nach Süden verschoben.\n«Wenn es nach Süden geht, wie es der Fall ist." is parsed to ["Es", "ist", "nicht", "dort", "wo", "es", "sein", "sollte", ". ", "Für", "diese", "Jahreszeit", "sollte", "es", "über", "dem", "Archipel", "sein", "und", "dennoch", "ist", "es", "nach", "Süden", "verschoben", ".\n«", "Wenn", "es", "nach", "Süden", "geht", ", ", "wie", "es", "der", "Fall", "ist", "."]
"""

INSTRUCTION_SUMMARIZE = """Summarize the following text in 2-3 words that can be used as a filename. The summary should be concise and descriptive.

Text to summarize:
{text}

Summary:"""

INSTRUCTION_FILTER_LANGUAGE = """From a german text, filter out words that are not suitable to be added to learning flashcards. For this, analyze the following text and identify words that are either:
    1. Person names
    2. Company names or websites
    3. Sections of English text (e.g. "what the fuck", "get by") that are not german
    4. Unique location names (e.g. Hotel Clarion, Berlin, Deutschland, Brandenburger Tor)
    5. Unique product names (e.g. iPhone, MacBook Pro, Samsung S22, YouTuber)
    6. Political descriptions (e.g. CDU, SPD, etc)
    7. Unique event names (e.g. Oktoberfest, Berlinale, etc)
    8. Unique sports names (e.g. Bayern München, Borussia Dortmund, etc)
    9. Unique references to culture, history, geography, science, mathematics, music, and art (e.g. Die Blechtrommel, Zweiter Weltkrieg, Schwarzwald)
    10. Unique English expressions (e.g. "break the ice", "self-confident", "the newsletter")

    Return a single-level JSON array containing just words to be filtered from the text.

    Text to analyze: "{text}"
    """
    
INSTRUCTION_CATEGORIZE = """Given a title and the first words of a non-English video, characterize it and provide English subcategories and tags to label it.
    Return a single-level JSON array containing just 4-5 subcategories / tags that describe what type of video it is
    
    title: {title}
    text:
    {text}
    """
    
INSTRUCTION_ROOT_FORM = """For the german word '{word}' return a 2 element JSON dictionary that determines the "type" which is either "verb" if it could be a verb, "noun", "adjective", or if its neither "other".
    
    Also include a "key":
    - If it's neither verb, adjective or noun the key is the word itself (this is the case for e.g. "der", "dafür", "hallo", "gemacht", "in", "vom", "nun"). Dont include an article here, write it lowercase.
    - For verbs of any conjugation it is the root form. 
    - For nouns it is the singular (!) full noun including German article. If it shouldn't have an article, e.g. because it is a country or proper noun, return the word itself!
    - For adjectives also give the singular (!) male root form. If it's not an adjective, return the word itself
    """
    
INSTRUCTION_VERIFY_NEW_WORD = """You are a meticulous German lexicographer reviewing one candidate dictionary entry before it is saved. Another process already picked the root and generated its forms -- your job is only to review that output, not redo it.

root: "{root}" (type: {type})
forms: {forms}

Default to trusting this entry. Only set "definitely_not_valid" to true if you are CONFIDENT something below is actually wrong -- not merely unsure or if the word is simply rare, regional, or archaic:
1. "root" is not a real, correctly-spelled German word -- e.g. it's a proper name, brand, a foreign-language word, a misspelling, or a conjugated/inflected surface form rather than the canonical dictionary form.
2. One or more of "forms" is not actually a German inflection of THIS root -- e.g. it's a form of a different, unrelated word, a foreign-language word, an English gloss, or nonsense.

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