INSTRUCTION_HIGH_LEVEL_TAG = """
Given the title and tags of a video, assign it to exactly one of the following high-level categories:
Beauty & Fashion, Health & Fitness, Products & Tech, Gaming, Anime, Movies, Reactions & Commentary, Challenges & Experiments, Comedy, Travel, Documentaries, Cooking, Entertainment, Science, Politics, Finance, Cars, Other, History

Title: {title}
Tags: {tags}

Respond with only the high-level category name.
"""

INSTRUCTION_SUMMARIZE = """Summarize the following text in 2-3 words that can be used as a filename. The summary should be concise and descriptive.

Text to summarize:
{text}

Summary:"""

INSTRUCTION_TRANSLATE = """Translate the following {language} text into english. Return just the text.

{text}
"""