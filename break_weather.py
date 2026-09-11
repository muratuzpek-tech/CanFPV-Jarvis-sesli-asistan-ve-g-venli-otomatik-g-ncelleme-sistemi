p = 'actions/weather_report.py'
c = open(p, encoding='utf-8').read()
target = "def weather_action"
idx = c.find(target)
if idx == -1:
    print('weather_action not found!')
    exit()
after_def = c.find('\n', idx) + 1
first_line_start = after_def
indent = ''
while first_line_start < len(c) and c[first_line_start] in ' \t':
    indent += c[first_line_start]
    first_line_start += 1
new_line = indent + "raise RuntimeError('Intentional test error for self-heal')\n"
c = c[:after_def] + new_line + c[after_def:]
open(p, 'w', encoding='utf-8').write(c)
print('weather_report.py broken intentionally')
