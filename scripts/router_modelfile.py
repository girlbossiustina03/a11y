"""Copy the installed base's TEMPLATE/PARAMETER directives without its FROM."""
import argparse
from pathlib import Path
import re


def make_modelfile(source, gguf):
    # Preserve multiline TEMPLATE byte-for-byte, including directive-looking lines.
    lines = source.splitlines(keepends=True)
    result, in_template, templates = [], False, 0
    for line in lines:
        if in_template:
            result.append(line)
            if '"""' in line:
                in_template = False
        elif re.match(r'^TEMPLATE\s', line):
            result.append(line)
            templates += 1
            in_template = line.count('"""') % 2 == 1
        elif re.match(r'^PARAMETER\s', line):
            result.append(line)
    if templates != 1 or in_template:
        raise ValueError('Expected one complete base TEMPLATE')
    if not any(line.startswith('PARAMETER ') for line in result):
        raise ValueError('Base PARAMETERS missing')
    return f'FROM {gguf}\n' + ''.join(result).rstrip() + '\n'


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('gguf')
    p.add_argument('output', type=Path)
    a = p.parse_args()
    a.output.write_text(make_modelfile(a.source.read_text(), a.gguf))
