from dataclasses import dataclass
@dataclass
class Circle:
    r: float
@dataclass
class Rect:
    w: float
    h: float
def area(s):
    match s:
        case Circle(r): return 3.14159 * r * r
        case Rect(w, h): return w * h
