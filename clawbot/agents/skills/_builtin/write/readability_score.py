META = {
    "name": "readability_score", "builtin": True,
    "description": "Flesch-Kincaid grade level + reading ease. Aim for grade 6-8, ease 60-70 for marketing copy.",
    "params": {"text": "str"},
    "returns": {"grade_level": "float", "reading_ease": "float"},
    "cost_estimate_usd": 0.0,
}


async def run(ctx, text: str) -> dict:
    import re as _re
    sentences = max(1, len(_re.findall(r"[.!?]+", text)))
    words_list = _re.findall(r"\b\w+\b", text)
    words = max(1, len(words_list))
    syllables = sum(_count_syl(w) for w in words_list) or 1
    asl = words / sentences
    asw = syllables / words
    grade = 0.39 * asl + 11.8 * asw - 15.59
    ease = 206.835 - 1.015 * asl - 84.6 * asw
    return {"grade_level": round(grade, 2), "reading_ease": round(ease, 2)}


def _count_syl(word: str) -> int:
    w = word.lower()
    vowels = "aeiouy"
    count = 0
    prev_vowel = False
    for ch in w:
        is_vowel = ch in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    if w.endswith("e"):
        count = max(1, count - 1)
    return max(1, count)
