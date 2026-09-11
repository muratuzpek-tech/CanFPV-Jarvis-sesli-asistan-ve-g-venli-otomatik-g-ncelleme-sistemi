Set WshShell = CreateObject("WScript.Shell")
Set lnk = WshShell.CreateShortcut("C:\Users\Murat\Desktop\Jarvis.lnk")
lnk.TargetPath = "C:\Users\Murat\Desktop\CanFPV_Jarvis_v3\CanFPV Jarvis v3\venv\Scripts\python.exe"
lnk.Arguments = "main.py"
lnk.WorkingDirectory = "C:\Users\Murat\Desktop\CanFPV_Jarvis_v3\CanFPV Jarvis v3"
lnk.Description = "MuratJarvis AI Assistant"
lnk.Save