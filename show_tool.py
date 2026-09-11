p = 'main.py'
c = open(p, encoding='utf-8').read()
lines = c.splitlines()
for i in range(695, 855):
    if i < len(lines):
        print(f'{i+1}: {lines[i]}')
