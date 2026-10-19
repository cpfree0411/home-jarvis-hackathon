"""Text normalisation and the family-safe topic filter shared by the research modules."""
import re
import unicodedata

QUERY_MAX = 80

# Adult-only subjects are refused before any lookup, and adult-classified
# evidence is dropped before the model sees it. The gallery is all-ages.
ADULT_RE = re.compile(
    r"hentai|eroge|\bero\b|r-?18|nsfw|porn|\bxxx\b|adult\s*(?:video|game|anime|manga|visual)|erotic|"
    r"\bsex(?:ual(?:ly)?\s+explicit)?\b|18\+|x-rated|adults?\s+only|アダルト|エロ|成人向け|18禁",
    re.I,
)
ADULT_GENRES = {"hentai", "ecchi"}


def clean(value, limit=600):
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKC", value[:20000])
    value = "".join(c if c in "\n" or unicodedata.category(c)[0] != "C" else " " for c in value)
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r"\s*\n\s*", "\n", value).strip()
    return value[:limit].rstrip()


def normalize_query(value):
    value = clean(value, 400).replace("\n", " ")
    value = re.sub(r"[<>{}\[\]\\|`\"]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()[:QUERY_MAX].strip()
    if not any(c.isalnum() for c in value):
        return ""
    return value


def query_key(query):
    return "".join(c for c in unicodedata.normalize("NFKC", query).casefold() if c.isalnum())


def is_adult_text(*values):
    return any(isinstance(v, str) and ADULT_RE.search(v) for v in values)
