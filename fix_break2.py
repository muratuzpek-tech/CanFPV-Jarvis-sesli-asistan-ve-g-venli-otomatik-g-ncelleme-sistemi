p = 'actions/weather_report.py'
c = open(p, encoding='utf-8').read()

# Remove ALL KASITLI lines
lines = c.splitlines()
clean = []
for line in lines:
    if 'KASITLI' not in line:
        clean.append(line)

# Fix line 6 if broken (should be "    parameters: dict,")
for i, line in enumerate(clean):
    if line.strip().startswith('parameters:') and 'dict' not in line:
        clean[i] = '    parameters: dict,'

c = '\n'.join(clean)

# Now insert raise INSIDE function, after "city = parameters.get"
lines = c.splitlines()
new_lines = []
for line in lines:
    new_lines.append(line)
    if 'city     = parameters.get' in line:
        new_lines.append('    raise RuntimeError("KASITLI_TEST")')

c = '\n'.join(new_lines)
open(p, 'w', encoding='utf-8').write(c)
print('WEATHER FIXED + BROKEN CORRECTLY')
