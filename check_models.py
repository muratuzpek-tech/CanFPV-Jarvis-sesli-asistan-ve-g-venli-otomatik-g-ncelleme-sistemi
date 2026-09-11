# Check what model self_heal uses now
p = 'actions/self_heal.py'
c = open(p, encoding='utf-8').read()
for line in c.splitlines():
    if 'model' in line.lower() and 'gemini' in line.lower():
        print('Current model:', line.strip())

# Check what model main.py uses for Live API
p2 = 'main.py'
c2 = open(p2, encoding='utf-8').read()
for line in c2.splitlines():
    if 'model' in line.lower() and ('gemini' in line.lower() or 'flash' in line.lower()):
        print('Main model:', line.strip())
