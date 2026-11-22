Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "c:\Users\User\twfin"
' 在背景無視窗啟動 Python 伺服器 (不跳出黑色視窗)
WshShell.Run "cmd /c netstat -ano | findstr :8765 >nul || python c:\Users\User\twfin\backend\server.py", 0, False
