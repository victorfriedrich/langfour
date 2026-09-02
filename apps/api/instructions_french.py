INSTRUCTION_VERBS = """Generate all French conjugations (simple tenses) for the verb {word} as a compact JSON dictionary. Also include the passé composé form. Return ONLY the JSON object with exactly these keys: "présent", "imparfait", "passé_simple", "futur", "conditionnel", "participe_passé", "gérondif".

Answer structure:
{{
  "présent": [],
  "imparfait": [],
  "passé_simple": [],
  "futur": [],
  "conditionnel": [],
  "participe_passé": "string",
  "gérondif": "string"
}}"""

INSTRUCTION_VERB_COMPLETE = """Generate the French gérondif for the verb {word} as a JSON entry. Return ONLY the JSON object with key "gérondif".

Answer structure:
{{
  "gérondif": "string"
}}"""

INSTRUCTION_NOUNS = """Generate a JSON array of the singular and plural forms of the French noun {word}, without any article. Return ONLY the JSON array.

Examples:
["lettre", "lettres"]
["centre", "centres"]
["père", "pères"]"""

INSTRUCTION_ADJECTIVE = """Generate a JSON array of the four forms of the French adjective {word}: [masculine singular, masculine plural, feminine singular, feminine plural]. Return ONLY the JSON array.

Example:
["anglais", "anglais", "anglaise", "anglaises"]"""

INSTRUCTION_GROUP = """Parse the following French text into small JSON string groups [g1, g2, ..., gn]:
- Verbal groups include pronouns and tense markers ("s'est arrêté", "a annoncé", "est publié").
- Noun groups include their article ("le concert", "la maison").
- Other words are single-token groups, unless part of a fixed expression ("à travers", "chacun").
- Punctuation and special characters each form their own group.

Return a flat JSON array of strings.

Text to parse:
{text}"""

INSTRUCTION_SUMMARIZE = """Summarize the following French text in 2–3 words suitable for a filename. Return ONLY the summary text.

Text to summarize:
{text}

Summary:"""

INSTRUCTION_FILTER_LANGUAGE = """From a French text, filter out words that are not suitable for flashcards. Identify names, brands, English segments, unique places, products, political entities, events, sports teams, or cultural references.

Return ONLY a JSON array of the filtered words.

Text to analyze: "{text}"""

INSTRUCTION_ROOT_FORM = """For the word '{word}', return a JSON object with:
- "type": one of "verb", "noun", "adjective", or "other".
- "key":
  - for verbs: the infinitive,
  - for nouns: the singular form with article ("le", "la", or "l'"),
  - for adjectives: the masculine singular,
  - otherwise: the word itself.

Return ONLY the JSON object.

Example:
{{"type":"verb","key":"aller"}}"""

INSTRUCTION_VERIFY_NEW_WORD = """You are a meticulous French lexicographer reviewing one candidate dictionary entry before it is saved. Another process already picked the root and generated its forms -- your job is only to review that output, not redo it.

root: "{root}" (type: {type})
forms: {forms}

Default to trusting this entry. Only set "definitely_not_valid" to true if you are CONFIDENT something below is actually wrong -- not merely unsure or if the word is simply rare, regional, or archaic:
1. "root" is not a real, correctly-spelled French word -- e.g. it's a proper name, brand, a foreign-language word, a misspelling, or a conjugated/inflected surface form rather than the canonical dictionary form.
2. One or more of "forms" is not actually a French inflection of THIS root -- e.g. it's a form of a different, unrelated word, a foreign-language word, an English gloss, or nonsense.

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

INSTRUCTION_VERIFY_LANGUAGE = """From a list of words, identify those that are not valid French words: includes misspellings, non-French terms, names, brands, English words, unique names, or acronyms. Words are more likely to be not valid than they're valid.

Return ONLY a JSON array of problematic words.

Words:
{word_list}"""
