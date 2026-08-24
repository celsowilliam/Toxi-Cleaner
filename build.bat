@echo off
REM ============================================================
REM  Gera o executavel unico (gc_toxicidade_bot.exe)
REM  Rode isso UMA VEZ, num Windows com Python instalado.
REM  Depois disso, so o .exe (dentro da pasta dist\) precisa
REM  ser distribuido para o resto da equipe - eles NAO precisam
REM  ter Python instalado.
REM ============================================================

python -m venv venv
call venv\Scripts\activate.bat

pip install -r requirements.txt

pyinstaller --noconfirm --onefile --windowed ^
  --name gc_toxicidade_bot ^
  --collect-all selenium ^
  app.py

REM O config.json fica FORA do .exe de proposito, para poder editar a
REM whitelist/blacklist de dominios sem precisar gerar o .exe de novo.
copy config.json dist\config.json

echo.
echo ============================================================
echo Pronto! Tudo que a equipe precisa esta em: dist\
echo   - gc_toxicidade_bot.exe
echo   - config.json
echo Copie a pasta dist\ inteira (ou zipe) e distribua para a equipe.
echo Na primeira execucao, cada pessoa vai logar uma vez no navegador
echo que abrir - o login fica salvo na pasta browser_profile que sera
echo criada do lado do .exe.
echo ============================================================
pause
