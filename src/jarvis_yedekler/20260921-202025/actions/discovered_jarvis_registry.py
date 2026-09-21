"""discovered_jarvis_registry.py — KALDIRILDI (2026-09-16).

Bu dosya GitHub kesif hattiyla ("jarvis tool" sorgusu) otomatik bulunup
entegre edilmisti, ama ismine ragmen bu Jarvis projesiyle hicbir ilgisi
yoktu: AWS Secrets Manager'dan sir okuyup Kubernetes ExternalSecret YAML'i
ureten, boto3 + gercek bir AWS hesabi/kimlik bilgisi gerektiren, tamamen
alakasiz bir arac oldugu tespit edildi (kullanici onayiyla kaldirildi).

actions/tools_kopru.py'nin ALLOWED_TOOLS / TOOL_DESCRIPTIONS listelerinden
cikarildi - artik hicbir yerden cagrilmiyor. Bu dosyanin kendisi, cihaza
uzaktan dosya SILME araci bulunmadigi icin fiziksel olarak silinemedi;
icerigi bilerek bu kisa aciklamayla degistirildi ki hem "olu kod" olarak
karisiklik yaratmasin hem de Jarvis'in kendi self-improve dongusu bunu
tekrar "gelistirilecek" bir taslak sanip uzerinde calismasin.

Guvenle elle silinebilir: actions/discovered_jarvis_registry.py
"""
