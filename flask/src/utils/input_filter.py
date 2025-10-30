import re


def contains_illegal_contents(text):
    if contains_cpr_number(text):
        return True, "Det ser ud til, at du har indtastet et CPR-nummer. Af sikkerhedsmæssige årsager bør du undgå at dele personlige oplysninger."
    return False, "OK"


def contains_cpr_number(text):
    cpr_pattern = re.compile(r'((((0[1-9]|[12][0-9]|3[01])(0[13578]|10|12)(\d{2}))|(([0][1-9]|[12][0-9]|30)(0[469]|11)(\d{2}))|((0[1-9]|1[0-9]|2[0-8])(02)(\d{2}))|((29)(02)(00))|((29)(02)([2468][048]))|((29)(02)([13579][26])))[-]*\d{4})', re.MULTILINE)
    return cpr_pattern.search(text) is not None
