Set objShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
stateDir = "C:\HomisKarteWriter"
errLog = stateDir & "\startup_error.log"
pyw = "C:\Users\setup\AppData\Local\Programs\Python\Python314\pythonw.exe"
launcher = scriptDir & "\launch_gui.py"

If Not fso.FolderExists(stateDir) Then
    On Error Resume Next
    fso.CreateFolder stateDir
    On Error GoTo 0
End If

Function AppendErr(msg)
    On Error Resume Next
    Dim ts
    Set ts = fso.OpenTextFile(errLog, 8, True)
    ts.WriteLine Now & " " & msg
    ts.Close
    On Error GoTo 0
End Function

If Not fso.FileExists(pyw) Then
    AppendErr "pythonw.exe not found: " & pyw
    WScript.Quit 1
End If

If Not fso.FileExists(launcher) Then
    AppendErr "launch_gui.py not found: " & launcher
    WScript.Quit 1
End If

cmd = """" & pyw & """ """ & launcher & """"
objShell.Run cmd, 0, False
