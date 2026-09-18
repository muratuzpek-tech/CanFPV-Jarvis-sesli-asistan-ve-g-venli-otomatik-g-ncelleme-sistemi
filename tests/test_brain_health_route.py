# paket 'pip install -e .' ile kurulu; sys.path hilesine gerek yok
from jarvis.main import JarvisLive
import jarvis.core.brain_orchestrator as bo

calls = []
def fake_health(parameters=None, player=None):
    calls.append((parameters, player))
    return 'AI Beyin Takımı sağlık durumu: tüm beyinler idle.'
bo.brain_team_tool = fake_health

class UI:
    def write_log(self, value):
        calls.append(('log', value))

obj = JarvisLive.__new__(JarvisLive)
obj._loop = object()
obj.session = object()
obj.ui = UI()
obj.speak = lambda value: calls.append(('speak', value))
obj._on_text_command('AI takımının sağlık durumunu göster.')
assert calls and calls[0][0] == {'action': 'health'}
assert any(item[0] == 'speak' and 'BRAIN_TEAM_HEALTH_SONUC' in item[1] for item in calls if isinstance(item, tuple))
print('BRAIN_HEALTH_ROUTE_OK')
