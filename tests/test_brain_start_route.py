# paket 'pip install -e .' ile kurulu; sys.path hilesine gerek yok
from jarvis.main import JarvisLive
import jarvis.core.brain_orchestrator as bo

calls = []
def fake_start(parameters=None, player=None):
    calls.append((parameters, player))
    return 'AI beyin takımı görevlendirildi (id: test1234)'
bo.brain_team_tool = fake_start

class UI:
    def write_log(self, value):
        calls.append(('log', value))

obj = JarvisLive.__new__(JarvisLive)
obj._loop = object()
obj.session = object()
obj.ui = UI()
obj.speak = lambda value: calls.append(('speak', value))
obj._on_text_command('AI takımına Türkiye teknoloji sektörünü araştır ve kısa özet hazırla.')
assert calls and calls[0][0]['action'] == 'start'
assert 'Türkiye teknoloji' in calls[0][0]['goal']
assert any(item[0] == 'speak' and 'BRAIN_TEAM_START_SONUC' in item[1] for item in calls if isinstance(item, tuple))
print('BRAIN_START_ROUTE_OK')
