@echo off
chcp 65001 >nul
cd /d "c:\Users\User\twfin"
echo ====================================================================
echo 正在檢查並啟動「台灣資金流向互動式視覺研究中心 ＆ ETF 投資決策中心」...
echo ====================================================================
wscript.exe "c:\Users\User\twfin\start_background_silent.vbs"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765/?v=live"
echo 已在瀏覽器開啟 http://127.0.0.1:8765 ！背景服務將持續運行（可關閉此視窗）。
timeout /t 3 >nul
