import re


def extract_number(text):
    match = re.search(r"\b(\d+)\b", text)
    if match:
        return int(match.group(1))
    else:
        return None
