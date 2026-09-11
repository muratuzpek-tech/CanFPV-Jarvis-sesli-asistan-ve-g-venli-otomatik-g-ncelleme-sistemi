p = 'actions/weather_report.py'
c = open(p, encoding='utf-8').read()
# once yanlis eklenen satiri kaldir
c = c.replace("    raise RuntimeError('Intentional test error for self-heal')\n", '')
# simdi dogru yere ekle: city = parameters.get satirindan sonra
target = 'city     = parameters.get("city")'
idx = c.find(target)
if idx == -1:
    target2 = 'city = parameters.get("city")'
    idx = c.find(target2)
if idx == -1:
    print('target line not found!')
    exit()
end_of_line = c.find('\n', idx) + 1
new_line = '    raise RuntimeError("Intentional test error for self-heal")\n'
c = c[:end_of_line] + new_line + c[end_of_line:]
open(p, 'w', encoding='utf-8').write(c)
print('weather_report.py broken correctly - RuntimeError after city line')
