"""
Units as UCUM codes (https://ucum.org), the subset fspm-TF accepts: SI and common atoms, metric prefixes on the
metric ones, products ('.'), quotients ('/'), integer exponents, parentheses, annotations ({...}, dimensionless) and
'1'. dimension(code) gives a unit's dimension, to check that two units are convertible, and conversion_factor the
factor from one to the other::

    dimension("mm3/(s.MPa)") == dimension("m4.s.kg-1")      True: the same physical dimension
    conversion_factor("g", "kg")                            0.001: a value in g times it is in kg
"""
import math
import re

# Dimensions: length, mass, time, temperature, amount, luminous intensity, current
BASE = ("L", "M", "T", "Θ", "N", "J", "I")


def _dims(**exponents) -> tuple:
    return tuple(exponents.get(name, 0) for name in ("L", "M", "T", "Th", "N", "J", "I"))


NONE = _dims()
METRIC_ATOMS = {
    "m": _dims(L=1), "g": _dims(M=1), "s": _dims(T=1), "K": _dims(Th=1), "mol": _dims(N=1), "cd": _dims(J=1),
    "A": _dims(I=1), "rad": NONE, "sr": NONE, "Hz": _dims(T=-1), "N": _dims(M=1, L=1, T=-2),
    "Pa": _dims(M=1, L=-1, T=-2), "J": _dims(M=1, L=2, T=-2), "W": _dims(M=1, L=2, T=-3), "C": _dims(I=1, T=1),
    "V": _dims(M=1, L=2, T=-3, I=-1), "Ohm": _dims(M=1, L=2, T=-3, I=-2), "S": _dims(M=-1, L=-2, T=3, I=2),
    "F": _dims(M=-1, L=-2, T=4, I=2), "T": _dims(M=1, T=-2, I=-1), "Wb": _dims(M=1, L=2, T=-2, I=-1),
    "lm": _dims(J=1), "lx": _dims(J=1, L=-2), "Bq": _dims(T=-1), "Gy": _dims(L=2, T=-2), "Sv": _dims(L=2, T=-2),
    "L": _dims(L=3), "l": _dims(L=3), "bar": _dims(M=1, L=-1, T=-2), "ar": _dims(L=2), "t": _dims(M=1),
    "eq": _dims(N=1), "Cel": _dims(Th=1),
    "m[H2O]": _dims(M=1, L=-1, T=-2), "m[Hg]": _dims(M=1, L=-1, T=-2),     # pressures as heights: cm[H2O], mm[Hg]
}
ATOMS = dict(METRIC_ATOMS, **{
    "min": _dims(T=1), "h": _dims(T=1), "d": _dims(T=1), "wk": _dims(T=1), "mo": _dims(T=1), "a": _dims(T=1),
    "deg": NONE, "%": NONE, "[ppm]": NONE, "[ppb]": NONE,
})
# Each atom's magnitude in the coherent units m, g, s, K, mol, cd, A (g, not kg: prefixes apply to g)
MAGNITUDES = {
    "N": 1e3, "Pa": 1e3, "J": 1e3, "W": 1e3, "V": 1e3, "Ohm": 1e3, "S": 1e-3, "F": 1e-3, "T": 1e3, "Wb": 1e3,
    "L": 1e-3, "l": 1e-3, "bar": 1e8, "ar": 1e2, "t": 1e6, "eq": 1., "m[H2O]": 9.80665e6, "m[Hg]": 1.33322387415e8,
    "min": 60., "h": 3600., "d": 86400., "wk": 604800., "mo": 2629800., "a": 31557600., "deg": math.pi / 180,
    "%": 1e-2, "[ppm]": 1e-6, "[ppb]": 1e-9,
}
PREFIX_FACTORS = {"da": 1e1, "Y": 1e24, "Z": 1e21, "E": 1e18, "P": 1e15, "T": 1e12, "G": 1e9, "M": 1e6, "k": 1e3,
                  "h": 1e2, "d": 1e-1, "c": 1e-2, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15,
                  "a": 1e-18, "z": 1e-21, "y": 1e-24}
SPECIAL = {"Cel"}                                   # an offset scale: not allowed in products, quotients, powers
PREFIXES = ("da", "Y", "Z", "E", "P", "T", "G", "M", "k", "h", "d", "c", "m", "u", "n", "p", "f", "a", "z", "y")

_TOKEN = re.compile(r"\{[^{}]*\}|\(|\)|\.|/|[+-]?\d+|[A-Za-z]+\[[^\]]+\]|\[[^\]]+\]|%|[A-Za-z]+")


class UnitError(ValueError):
    pass


def _atom(text: str) -> tuple:
    """(dimension, special, magnitude) of a unit symbol, with its prefix."""
    if text in ATOMS:
        return ATOMS[text], text in SPECIAL, MAGNITUDES.get(text, 1.)
    for prefix in PREFIXES:
        if text.startswith(prefix) and text[len(prefix):] in METRIC_ATOMS:
            atom = text[len(prefix):]
            return METRIC_ATOMS[atom], atom in SPECIAL, PREFIX_FACTORS[prefix] * MAGNITUDES.get(atom, 1.)
    raise UnitError(f"unknown unit symbol '{text}'")


def dimension(code: str) -> tuple:
    """The dimension of the UCUM *code* (exponents of L, M, T, Θ, N, J, I); raises UnitError if not a unit fspm-TF
    accepts."""
    return _parse(code)[0]


def magnitude(code: str) -> float:
    """The size of the unit *code* in the coherent units m, g, s, K, mol, cd, A (e.g. 'kPa': 1e6 g.m-1.s-2)."""
    return _parse(code)[2]


def conversion_factor(code: str, other: str) -> float:
    """The factor converting a value in *code* to *other* (value_in_other = value_in_code * factor); UnitError if
    they are not convertible, or if one is Cel and the other not (an offset scale: no factor)."""
    dims, special, size = _parse(code)
    other_dims, other_special, other_size = _parse(other)
    if dims != other_dims:
        raise UnitError(f"'{code}' and '{other}' are not convertible (different dimensions)")
    if special != other_special:
        raise UnitError(f"'{code}' and '{other}': Cel is an offset scale, converted to K by adding 273.15, not by a "
                        "factor")
    return size / other_size


def _parse(code: str) -> tuple:
    """(dimension, special, magnitude) of the UCUM *code*."""
    if not isinstance(code, str) or not code or code != code.strip() or " " in code:
        raise UnitError(f"'{code}' is not a UCUM code (no spaces: write 'mol/(m2.s)' or 'mol.m-2.s-1')")
    tokens = _TOKEN.findall(code)
    if "".join(tokens) != code:
        raise UnitError(f"'{code}' is not a UCUM code")
    position = 0

    def term():
        nonlocal position
        total, special_seen, count, size = [0] * 7, False, 0, 1.
        sign = 1
        if position < len(tokens) and tokens[position] == "/":
            sign, position = -1, position + 1
        while True:
            dims, special, factor = component()
            count += 1
            special_seen = special_seen or special
            total = [a + sign * b for a, b in zip(total, dims)]
            size = size * factor if sign > 0 else size / factor
            if position < len(tokens) and tokens[position] in (".", "/"):
                sign = 1 if tokens[position] == "." else -1
                position += 1
                continue
            break
        if special_seen and count > 1:
            raise UnitError(f"'{code}': Cel (a temperature scale) cannot be combined with other units; use K")
        return tuple(total), special_seen, size

    def component():
        nonlocal position
        if position >= len(tokens):
            raise UnitError(f"'{code}' ends too early")
        token = tokens[position]
        position += 1
        if token == "(":
            dims, special, factor = term()
            if position >= len(tokens) or tokens[position] != ")":
                raise UnitError(f"'{code}': unbalanced parenthesis")
            position += 1
        elif token.startswith("{"):
            return NONE, False, 1.
        elif re.fullmatch(r"[+-]?\d+", token):
            if int(token) != 1 and not token.lstrip("+-").startswith("10"):
                raise UnitError(f"'{code}': numbers other than 1 are not units")
            return NONE, False, float(int(token))
        elif token in (".", "/", ")"):
            raise UnitError(f"'{code}': unexpected '{token}'")
        else:
            dims, special, factor = _atom(token)
        if position < len(tokens) and re.fullmatch(r"[+-]?\d+", tokens[position]):
            exponent = int(tokens[position])
            position += 1
            if special:
                raise UnitError(f"'{code}': Cel cannot have an exponent")
            dims = tuple(exponent * value for value in dims)
            factor = factor ** exponent
        if position < len(tokens) and tokens[position].startswith("{"):
            position += 1
        return dims, special, factor

    parsed = term()
    if position != len(tokens):
        raise UnitError(f"'{code}': unexpected '{tokens[position]}'")
    return parsed


def is_valid(code: str) -> bool:
    try:
        dimension(code)
        return True
    except UnitError:
        return False


def convertible(code: str, other: str) -> bool:
    """Whether the two UCUM codes have the same dimension (a value in one can be converted to the other)."""
    return dimension(code) == dimension(other)
