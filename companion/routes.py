"""Remembered routes: how past computer tasks reached their goal, offered as a hint next time.

A small local file (<data>/routes.json, at most LIMIT routes, nothing leaves the computer).
Only finished tasks are kept, as their action types and the labels of what was clicked or
opened, never typed text or screen contents. A new goal recalls the route of the most
similar earlier goal (most of its words in common); the model may follow it when the screen
matches and ignores it otherwise. Clearing learned preferences clears these too.
"""
import json
import os
import re
import time

from .paths import data_dir

LIMIT = 100
SIMILAR = 0.6   # share of words two goals need in common
STOPWORDS = set('a an the my me to for in on of and or please can you could would i it this that is are be what '
                'how do does show open go find check tell'.split())


def path():
    return data_dir()/'routes.json'


def load():
    try:
        value = json.loads(path().read_text())
        return [entry for entry in value if isinstance(entry, dict) and isinstance(entry.get('steps'), list)] if isinstance(value, list) else []
    except (OSError, ValueError):
        return []


def save(entries):
    try:
        path().parent.mkdir(parents=True, exist_ok=True)
        path().write_text(json.dumps(entries[-LIMIT:], ensure_ascii=False, indent=1))
    except OSError:
        pass


def goal_words(goal):
    """What a goal is about: its words, without quoted text, numbers or filler ("compute 812 times 7"
    and "compute 40 times 3" are the same route)."""
    goal = re.sub(r'"[^"]*"|“[^”]*”', ' ', goal.casefold())
    return {w for w in re.findall(r'[^\W\d_]+', goal) if w not in STOPWORDS and len(w) > 1}


def step_of(receipt):
    """One step as remembered: its type and a short label, or None to leave it out."""
    kind = str(receipt.get('type') or '')
    if kind in ('', 'wait', 'type_text') or receipt.get('status') in ('failed', 'refused', 'rejected'):
        return None
    label = re.sub(r'\s+', ' ', str(receipt.get('label') or receipt.get('key') or '')).strip()
    if len(label) > 48:
        return None  # long labels are screen text, not a route
    return {'type': kind, 'label': label}


def remember(goal, receipts, now=None):
    """Keep the route of a finished task (replacing the one for the same goal). Not when a step
    changed nothing or repeated the one before: "done" after clicking "All iCloud" three times was
    saved and handed back as a route to follow (live)."""
    if os.getenv('A11Y_ROUTES', '1') == '0':
        return False
    if any(receipt.get('effect') == 'nothing changed on screen' for receipt in receipts):
        return False
    words = goal_words(goal)
    steps = [step for step in map(step_of, receipts) if step]
    if not words or not steps or len(steps) > 12 or any(a == b for a, b in zip(steps, steps[1:])):
        return False
    entries = [entry for entry in load() if set(entry.get('words', [])) != words]
    entries.append({'words': sorted(words), 'goal': goal[:160], 'steps': steps, 'at': int(now or time.time())})
    save(entries)
    return True


def recall(goal):
    """{'goal', 'steps'} of the most similar remembered goal, or None."""
    if os.getenv('A11Y_ROUTES', '1') == '0':
        return None  # tests: never the routes a live run left in .data
    words = goal_words(goal)
    if not words:
        return None
    best, score = None, 0.0
    for entry in load():
        known = set(entry.get('words', []))
        if not known:
            continue
        similarity = len(words & known)/len(words | known)
        if similarity > score:
            best, score = entry, similarity
    if best is None or score < SIMILAR:
        return None
    return {'goal': best['goal'], 'steps': [(s['type']+(' '+s['label'] if s.get('label') else ''))[:60] for s in best['steps']]}


def forget():
    try:
        path().unlink()
    except OSError:
        pass
