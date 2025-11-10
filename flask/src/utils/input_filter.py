import re


def redact_content(text):
    filtered_content = get_filter_content(text)
    redacted_text = text
    for content in filtered_content:
        redacted_text = redacted_text.replace(content, f"[REDACTED #{filtered_content.index(content) + 1}]")
    return redacted_text


def get_filter_content(text):
    filtered_content = []
    filtered_content.extend(contains_cpr_number(text))
    return filtered_content


def contains_cpr_number(text):
    cpr_pattern = re.compile(r'((((0[1-9]|[12][0-9]|3[01])(0[13578]|10|12)(\d{2}))|(([0][1-9]|[12][0-9]|30)(0[469]|11)(\d{2}))|((0[1-9]|1[0-9]|2[0-8])(02)(\d{2}))|((29)(02)(00))|((29)(02)([2468][048]))|((29)(02)([13579][26])))[-]*\d{4})', re.MULTILINE)
    return [match.group(0) for match in cpr_pattern.finditer(text)]
