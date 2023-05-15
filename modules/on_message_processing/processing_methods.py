import re

import demoji


def e_replace(string):
    string_new = string.replace('ё', 'е')
    return string_new


def em_replace(string):
    emoji = demoji.findall(string)
    for i in emoji:
        unicode = i.encode('unicode-escape').decode('ASCII')
        string = string.replace(i, unicode)
    return string


def string_found(string1, string2):
    search = re.search(r"\b" + re.escape(string1) + r"\b", string2)
    if search:
        return True
    return False