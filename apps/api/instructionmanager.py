import instructions_italian, instructions_spanish, instructions_german, instructions_french, instructions_nonlocalized


INSTRUCTION_HIGH_LEVEL_TAG = instructions_nonlocalized.INSTRUCTION_HIGH_LEVEL_TAG
INSTRUCTION_CATEGORIZE    = instructions_nonlocalized.INSTRUCTION_CATEGORIZE
INSTRUCTION_SUMMARIZE     = instructions_nonlocalized.INSTRUCTION_SUMMARIZE
INSTRUCTION_TRANSLATE     = instructions_nonlocalized.INSTRUCTION_TRANSLATE

INSTRUCTION_VERBS = {
    'it': instructions_italian.INSTRUCTION_VERBS,
    'es': instructions_spanish.INSTRUCTION_VERBS,
    'de': instructions_german.INSTRUCTION_VERBS,
    'fr': instructions_french.INSTRUCTION_VERBS,
}

INSTRUCTION_VERB_COMPLETE = {
    'it': instructions_italian.INSTRUCTION_VERB_COMPLETE,
    'es': instructions_spanish.INSTRUCTION_VERB_COMPLETE,
    'de': instructions_german.INSTRUCTION_VERB_COMPLETE,
    'fr': instructions_french.INSTRUCTION_VERB_COMPLETE,
}

INSTRUCTION_NOUNS = {
    'it': instructions_italian.INSTRUCTION_NOUNS,
    'es': instructions_spanish.INSTRUCTION_NOUNS,
    'de': instructions_german.INSTRUCTION_NOUNS,
    'fr': instructions_french.INSTRUCTION_NOUNS,
}

INSTRUCTION_ADJECTIVE = {
    'it': instructions_italian.INSTRUCTION_ADJECTIVE,
    'es': instructions_spanish.INSTRUCTION_ADJECTIVE,
    'de': instructions_german.INSTRUCTION_ADJECTIVE,
    'fr': instructions_french.INSTRUCTION_ADJECTIVE,
}

INSTRUCTION_GROUP = {
    'it': instructions_italian.INSTRUCTION_GROUP,
    'es': instructions_spanish.INSTRUCTION_GROUP,
    'de': instructions_german.INSTRUCTION_GROUP,
    'fr': instructions_french.INSTRUCTION_GROUP,
}

INSTRUCTION_FILTER_LANGUAGE = {
    'it': instructions_italian.INSTRUCTION_FILTER_LANGUAGE,
    'es': instructions_spanish.INSTRUCTION_FILTER_LANGUAGE,
    'de': instructions_german.INSTRUCTION_FILTER_LANGUAGE,
    'fr': instructions_french.INSTRUCTION_FILTER_LANGUAGE,
}

INSTRUCTION_VERIFY_LANGUAGE = {
    'it': instructions_italian.INSTRUCTION_VERIFY_LANGUAGE,
    'es': instructions_spanish.INSTRUCTION_VERIFY_LANGUAGE,
    'de': instructions_german.INSTRUCTION_VERIFY_LANGUAGE,
    'fr': instructions_french.INSTRUCTION_VERIFY_LANGUAGE,
}

INSTRUCTION_ROOT_FORM = {
    'it': instructions_italian.INSTRUCTION_ROOT_FORM,
    'es': instructions_spanish.INSTRUCTION_ROOT_FORM,
    'de': instructions_german.INSTRUCTION_ROOT_FORM,
    'fr': instructions_french.INSTRUCTION_ROOT_FORM,
}

# A separate review step run AFTER INSTRUCTION_ROOT_FORM + the per-type
# INSTRUCTION_VERBS/NOUNS/ADJECTIVE generation -- it does not replace that
# pipeline, it checks the entry it produced (and generates the translation,
# which used to only be fetched lazily on first user lookup). Same check,
# called identically from every place a new dictionary entry gets written.
# See nlp_processing.verify_and_translate().
INSTRUCTION_VERIFY_NEW_WORD = {
    'it': instructions_italian.INSTRUCTION_VERIFY_NEW_WORD,
    'es': instructions_spanish.INSTRUCTION_VERIFY_NEW_WORD,
    'de': instructions_german.INSTRUCTION_VERIFY_NEW_WORD,
    'fr': instructions_french.INSTRUCTION_VERIFY_NEW_WORD,
}
