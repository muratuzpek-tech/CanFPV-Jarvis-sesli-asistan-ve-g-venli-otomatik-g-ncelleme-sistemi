import os, subprocess
desktop = os.path.join(os.path.expanduser("~"), "Desktop")
project = r"C:\Users\Murat\Desktop\CanFPV_Jarvis_v3\CanFPV Jarvis v3"
python = os.path.join(project, "venv", "Scripts", "python.exe")
vbs = f"""Set WshShell = CreateObject("WScript.Shell")
Set lnk = WshShell.CreateShortcut("{desktop}\\Jarvis.lnk")
lnk.TargetPath = "{python}"
lnk.Arguments = "main.py"
lnk.WorkingDirectory = "{project}"
lnk.Description = "MuratJarvis AI Assistant"
lnk.Save"""
vbs_path = os.path.join(project, "mk_link.vbs")
with open(vbs_path, "w", encoding="ascii", newline="\r\n") as f:
    f.write(vbs)
subprocess.run(["cscript", "//nologo", vbs_path], shell=True)
print("Jarvis.lnk created on Desktop!")
