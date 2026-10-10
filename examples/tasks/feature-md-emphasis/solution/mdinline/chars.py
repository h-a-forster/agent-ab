"""Character helpers."""
import unicodedata

ASCII_PUNCTUATION = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"


def escape_html(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def is_whitespace(c):
    """CommonMark 'Unicode whitespace': category Zs, tab, line feed, form feed, carriage return."""
    return c in "\t\n\f\r" or unicodedata.category(c) == "Zs"


def is_punctuation(c):
    """CommonMark 0.31 'Unicode punctuation': any P or S category character."""
    return c in ASCII_PUNCTUATION or unicodedata.category(c)[0] in "PS"
