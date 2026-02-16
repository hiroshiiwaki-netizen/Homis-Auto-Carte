Set objShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' VBSファイルと同じフォルダのgui.pyを起動
Dim scriptDir
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' pythonwをフルパスで起動（コンソール窓なし）
Dim cmd
cmd = """C:\Users\setup\AppData\Local\Programs\Python\Python314\pythonw.exe"" """ & scriptDir & "\gui.py"""
objShell.Run cmd, 0, False
