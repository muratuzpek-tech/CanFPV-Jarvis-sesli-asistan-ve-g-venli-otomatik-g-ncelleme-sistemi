# Fix 1: Weather - remove test error
p1 = 'actions/weather_report.py'
c1 = open(p1, encoding='utf-8').read()
c1 = c1.replace('    raise RuntimeError("KASITLI_TEST")\n', '', 1)
open(p1, 'w', encoding='utf-8').write(c1)
print('1. WEATHER FIXED')

# Fix 2: self_heal - use correct text model
p2 = 'actions/self_heal.py'
c2 = open(p2, encoding='utf-8').read()
# The native audio model cant do text generation
c2 = c2.replace('gemini-2.5-flash-preview-native-audio', 'gemini-2.0-flash-001')
open(p2, 'w', encoding='utf-8').write(c2)
print('2. SELF-HEAL MODEL FIXED')

# Fix 3: Check speak_error in main.py
p3 = 'main.py'
c3 = open(p3, encoding='utf-8').read()
lines = c3.splitlines()
for i, line in enumerate(lines):
    if 'speak_error' in line:
        print(f'3. speak_error at line {i+1}: {line.strip()}')
