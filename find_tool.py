p = 'main.py'
c = open(p, encoding='utf-8').read()
lines = c.splitlines()
for i, line in enumerate(lines):
    if 'result' in line and '=' in line and i > 600:
        print(f'{i+1}: {line}')
