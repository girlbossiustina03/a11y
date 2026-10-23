"""Plain arithmetic in code: answers "5 + 5?" without a model, an app or a task.

Only numbers, + - * / % ^ and parentheses are accepted, evaluated with a small
AST walker (never eval). The same parse yields the key sequence for Calculator
when the user explicitly asks to use it."""
import ast
import operator
import re

LEAD = re.compile(r'^\s*(?:please\s+)?(?:(?:what(?:\'s| is)|whats|how much is|calculate|compute|work out|solve|tell me)\s+)?', re.I)
WORDS = [(r'\bplus\b|\badd(?:ed to)?\b|\band\b', '+'), (r'\bminus\b|\bsubtract(?:ed from)?\b|\bless\b', '-'),
         (r'\btimes\b|\bmultiplied by\b|\bx\b|×', '*'), (r'\bdivided by\b|\bover\b|÷', '/'),
         (r'\bto the power of\b|\^', '**'), (r'\bpercent of\b', '/100*')]
ALLOWED = re.compile(r'^[\d\s.+\-*/%()]+$')
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.Mod: operator.mod, ast.Pow: operator.pow, ast.FloorDiv: operator.floordiv}


def expression(text):
    """The arithmetic expression a request consists of, or None if it asks anything else."""
    body = LEAD.sub('', text.strip()).rstrip('?.! ').strip()
    body = re.sub(r'^(?:the\s+)?(?:sum|total)\s+of\s+', '', body, flags=re.I)
    for pattern, symbol in WORDS:
        body = re.sub(pattern, symbol, body, flags=re.I)
    body = body.replace('=', '').strip()
    if not body or not ALLOWED.match(body) or not re.search(r'\d', body) or not re.search(r'\d\s*(\*\*|[+\-*/%])\s*[\d(]', body):
        return None
    try:
        evaluate(body)
    except (ValueError, ZeroDivisionError, SyntaxError, OverflowError):
        return None
    return re.sub(r'\s+', ' ', body)


def evaluate(expr):
    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = walk(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 1e6):
                raise ValueError('Exponent too large.')
            return OPS[type(node.op)](left, right)
        raise ValueError('Unsupported expression.')
    if len(expr) > 200:
        raise ValueError('Expression too long.')
    return walk(ast.parse(expr, mode='eval'))


def formatted(value):
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        value = int(value)
    if isinstance(value, float):
        value = round(value, 10)
    return '{:,}'.format(value) if isinstance(value, int) and abs(value) >= 10000 else str(value)


def answer(text):
    """'5 + 5 = 10' for a pure arithmetic request, else None."""
    expr = expression(text)
    if expr is None:
        return None
    try:
        return expr.replace('**', '^').replace('*', '×').replace('/', '÷')+' = '+formatted(evaluate(expr))
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


# Calculator buttons by accessible name: macOS AX descriptions and Windows UIA names.
KEY_NAMES = {
    '0': ('0', 'zero'), '1': ('1', 'one'), '2': ('2', 'two'), '3': ('3', 'three'), '4': ('4', 'four'),
    '5': ('5', 'five'), '6': ('6', 'six'), '7': ('7', 'seven'), '8': ('8', 'eight'), '9': ('9', 'nine'),
    '.': ('decimal', 'decimal separator', '.', 'point'), '+': ('add', 'plus', '+'), '-': ('subtract', 'minus', '−', '-'),
    '*': ('multiply', 'multiply by', 'times', '×', '*'), '/': ('divide', 'divide by', '÷', '/'),
    '=': ('equals', '=', 'equal'), 'clear': ('all clear', 'clear', 'ac', 'c', 'clear all'),
}


def keypad(goal):
    """Calculator key sequence for 'use Calculator to …' goals, or None.

    Only plain left-to-right sequences (no parentheses, powers or percent) are typed;
    others are left to the model."""
    if not re.search(r'\bcalculator\b', goal, re.I):
        return None
    tail = re.split(r'\bcalculator\b', goal, flags=re.I)[-1]
    tail = re.sub(r'^\s*(?:and|then|to|,)*\s*(?:sum|add|calculate|compute|do|work out|type|enter)?\s*', '', tail, flags=re.I)
    expr = expression(tail)
    if expr is None or re.search(r'[()%]|\*\*', expr):
        return None
    keys = ['clear']
    for token in re.findall(r'\d+(?:\.\d+)?|[+\-*/]', expr):
        keys.extend(token if token[0].isdigit() else [token])
    return keys+['='], expr


def find_key(key, controls):
    """The enabled control whose label names this key, matched exactly (case-insensitive)."""
    names = KEY_NAMES.get(key, (key,))
    for control in controls:
        label = (control.get('label') or '').strip().casefold()
        if label in names and control.get('enabled', True):
            return control
    return None
